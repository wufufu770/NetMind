from __future__ import annotations
import os
from ..schemas import TelemetrySnapshot, Diagnosis, HealingReport
from ..store import STORE

# 判定阈值。单位是「相对基线的倍数」或「绝对但有物理含义的分界」，
# 不是拍脑袋的绝对 Mbps —— 绝对 Mbps 阈值换个链路速率就失效。

LATENCY_DEGRADED_MS = 50.0        # 超过此值视为链路劣化（对照实验台：健康 ~0.2ms，注入后 ~120ms）
LOSS_LINK_DOWN = 0.9              # 丢包到这个程度等价于链路不可用
LOSS_DEGRADED = 0.05              # 超过此值视为劣化
THROUGHPUT_DROP_RATIO = 0.5       # 带宽跌到基线一半以下才算受限；无基线时不参与判定

# 真实探测需要知道「向谁打」。没配就是没法测，不猜。
PROBE_TARGET_ENV = 'NETMIND_PROBE_TARGET'
PROBE_COUNT_ENV = 'NETMIND_PROBE_COUNT'


def _real_snapshot() -> tuple[TelemetrySnapshot | None, str]:
    """真探测一次。返回 (快照, 原因)。拿不到就返回 (None, 原因)，绝不编数字。

    探测方式：从**目标设备上** ping 配置的探测点——这才是网络运维的真实测法
    （本地 ping 只能测到本地网卡的连通性）。复用 diagnose.lab_collector 里
    已验证过的报文解析。
    """
    target = os.getenv(PROBE_TARGET_ENV, '').strip()
    if not target:
        return None, f'未配置 {PROBE_TARGET_ENV}，没有可测量的探测点'
    try:
        count = int(os.getenv(PROBE_COUNT_ENV, '10'))
    except ValueError:
        count = 10

    from .transaction import build_driver
    driver = build_driver()
    # driver 自己的 collect 走 napalm，只给 facts/interfaces，没有延迟；
    # 这里要的是延迟与丢包，所以直接走它已建立的 SSH 连接下发 ping。
    if not hasattr(driver, '_connect'):
        return None, f'当前 driver（{getattr(driver, "name", "?")}）不支持 SSH 探测'
    try:
        conn = driver._connect()
        raw = conn.send_command(f'ping -c {count} -i 0.2 -W 2 {target}')
    except Exception as exc:
        return None, f'探测失败 {type(exc).__name__}: {str(exc)[:120]}'

    from ..diagnose.lab_collector import parse_ping, to_snapshot
    m = parse_ping(raw)
    if m.get('transmitted', 0) == 0:
        return None, '探测输出里没有报文统计，判定为未采到数据'
    return to_snapshot(m, source='real'), ''


# 模拟数据置信度折扣。刻意用独立系数而不是「样本数减半」——只有 1 个样本时
# 减半等于没减，折扣会静默失效。
SIM_SOURCE_DISCOUNT = 0.6


def _confidence(strength: float, sample_size: int, corroborated: bool = False,
                simulated: bool = False) -> float:
    """置信度由可观测状态推导（CONTRIBUTING 规则 2），不是写死的常数。

    strength ∈ [0,1] 证据强度；sample_size 是实际观测到的样本数；
    corroborated 表示有独立证据佐证（带宽相对基线也下降）。
    样本越少、证据越弱，置信度越低——这样这个数字才有信息量。

    佐证走独立的乘性增强而不是并入 strength：并入会被上限截断，
    把「有佐证」与「强度爆表」两种情形压成同一个值，佐证信号就丢了。
    """
    base = 0.5 + 0.4 * max(0.0, min(1.0, strength))
    size_factor = min(1.0, sample_size / 10.0)
    boost = 1.1 if corroborated else 1.0
    discount = SIM_SOURCE_DISCOUNT if simulated else 1.0
    return round(min(0.99, base * (0.7 + 0.3 * size_factor) * boost * discount), 3)


class TelemetryService:
    def __init__(self):
        self.fault='normal'; self.tick=0
        self._last_fallback=''      # 最近一次降级的原因；空串表示上次是真测的
    def inject(self, fault: str):
        self.fault=fault; STORE.log('experiment', f'fault injected: {fault}', 'warn')
        return {'fault': fault, 'ok': True}
    def _simulated(self) -> TelemetrySnapshot:
        """模拟器。保留是因为没有探测配置时演示与测试需要一条确定的路径。

        它的产出**必须**带 source='simulated'——主链路拿它冒充真数据是
        本项目明令禁止的事。
        """
        self.tick += 1
        if self.fault == 'congestion': return TelemetrySnapshot(latency_ms=68, packet_loss=0.018, throughput_mbps=32, alert=True, source='simulated')
        if self.fault == 'link_down': return TelemetrySnapshot(latency_ms=999, packet_loss=1.0, throughput_mbps=0, alert=True, source='simulated')
        if self.fault == 'guest_spike': return TelemetrySnapshot(latency_ms=55, packet_loss=0.008, throughput_mbps=118, alert=True, source='simulated')
        return TelemetrySnapshot(latency_ms=23+(self.tick%4), packet_loss=0.0002, throughput_mbps=82, alert=False, source='simulated')

    def sample(self, record: bool=True) -> TelemetrySnapshot:
        """主链路的遥测入口。优先真探测；探测不可用才降级到模拟。

        降级时会把原因记进审计，并让快照带 source='simulated'——
        调用方（面板、跑测报告、诚实表）据此就能知道这个数字不是测来的。
        """
        snap, why = _real_snapshot()
        if snap is not None:
            self._last_fallback = ''
            if record:
                STORE.record_telemetry(snap)
            return snap
        self._last_fallback = why
        STORE.log('telemetry', f'real probe unavailable, fell back to simulator: {why}', 'warn')
        snap = self._simulated()
        if record:
            STORE.record_telemetry(snap)
        return snap

    def provenance(self) -> dict:
        """这份遥测是真测的还是模拟的——供诚实表与跑测报告引用。"""
        return {
            'real': getattr(self, '_last_fallback', '') == '',
            'reason': getattr(self, '_last_fallback', ''),
            'probe_target': os.getenv(PROBE_TARGET_ENV, '').strip(),
        }
    def diagnose(self, snapshots=None, baseline_throughput_mbps: float | None = None) -> Diagnosis:
        snapshots=snapshots or STORE.telemetry[-3:]
        if not snapshots: return Diagnosis(type='normal')
        n=len(snapshots)
        last=snapshots[-1]
        # 模拟数据得出的结论，置信度打折：凭硬编码常量下的判断不该有高置信度。
        sim=str(getattr(last, 'source', '') or '') in ('simulated', 'synthetic')
        loss=float(last.packet_loss or 0.0)
        latency=float(last.latency_ms or 0.0)
        n=len(snapshots)

        # 带宽只在有基线时参与，且是相对判定；没有基线就不猜
        bw_drop=None
        if baseline_throughput_mbps and last.throughput_mbps:
            bw_drop = (baseline_throughput_mbps - last.throughput_mbps) / baseline_throughput_mbps

        if loss >= LOSS_LINK_DOWN:
            strength=min(1.0, loss)
            return Diagnosis(type='link_down',
                             evidence={'packet_loss':loss,'latency_ms':latency,**({'source':str(last.source)} if sim else {})},
                             confidence=_confidence(strength, n, simulated=sim))
        # 5%~90% 的丢包是「链路劣化」，不是「链路断开」——断链是 >= 90%。
        # 原来这段返回 link_down，模拟器永远测不到：它的拥塞态丢包只有 1.8%，
        # 落在 5% 以下。真实探测一上来就是 120ms+10% 丢包，当场打脸。
        if loss >= LOSS_DEGRADED:
            ev={'packet_loss':loss,'latency_ms':latency}
            if sim: ev['source']=str(last.source)
            return Diagnosis(type='congestion', evidence=ev,
                             confidence=_confidence(loss, n, simulated=sim))
        # 延迟劣化即可判定拥塞。带宽是佐证不是必要条件——实验台实测：
        # 注入 120ms 延迟不限速时带宽 18.66Mbps，与健康态 21.08 接近，
        # 说明「延迟升高」与「带宽受限」是独立的两件事。
        if latency > LATENCY_DEGRADED_MS:
            ev={'latency_ms':latency}
            if sim: ev['source']=str(last.source)
            strength=min(1.0, (latency - LATENCY_DEGRADED_MS) / LATENCY_DEGRADED_MS)
            corroborated = bool(bw_drop is not None and bw_drop >= THROUGHPUT_DROP_RATIO)
            if corroborated:
                ev['throughput_drop_ratio']=round(bw_drop,3)
            return Diagnosis(type='congestion', evidence=ev,
                             confidence=_confidence(strength, n, corroborated, simulated=sim))
        if bw_drop is not None and bw_drop >= THROUGHPUT_DROP_RATIO:
            return Diagnosis(type='anomaly_traffic',
                             evidence={'throughput_drop_ratio':round(bw_drop,3)},
                             confidence=_confidence(bw_drop, n, simulated=sim))
        return Diagnosis(type='normal')
    def heal(self, diagnosis: Diagnosis) -> HealingReport:
        """模拟路径的自愈。此前 success 恒为 True——把 fault 改回 normal 再采一次
        样就算「处置成功」，与是否真做了事无关。

        这里只做能在无外部依赖时做到的事，并如实标注 verified=False：
        它把 fault 置回 normal 后重采，能确认的只是「模拟器状态变了」，
        不是「真实链路恢复了」。真实闭环见 diagnose/closed_loop.py。
        """
        before=STORE.telemetry[-1] if STORE.telemetry else self.sample()
        action={'congestion':'启用备用路径并重新下发流表','link_down':'回滚故障链路策略并切换备用链路','anomaly_traffic':'应用访客限速与隔离策略','config_error':'回滚最近配置','normal':'无需动作'}[diagnosis.type]
        self.fault='normal'
        after=self.sample()
        report=HealingReport(
            action_taken=action, before_snapshot=before, after_snapshot=after,
            success=False, verified=False,
            improvement={'note': '模拟路径，未做真实重测，不构成成功证据'},
            summary=(f'{action}；模拟态重采（{after.source}）：{after.latency_ms}ms —— '
                     f'未做真实重测，不报成功。真实闭环见 diagnose/closed_loop.py'),
        )
        STORE.log('healing', report.summary, 'info')
        return report
TELEMETRY=TelemetryService()
