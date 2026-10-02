from __future__ import annotations
from ..schemas import TelemetrySnapshot, Diagnosis, HealingReport
from ..store import STORE

# 判定阈值。单位是「相对基线的倍数」或「绝对但有物理含义的分界」，
# 不是拍脑袋的绝对 Mbps —— 绝对 Mbps 阈值换个链路速率就失效。
LATENCY_DEGRADED_MS = 50.0        # 超过此值视为链路劣化（对照实验台：健康 ~0.2ms，注入后 ~120ms）
LOSS_LINK_DOWN = 0.9              # 丢包到这个程度等价于链路不可用
LOSS_DEGRADED = 0.05              # 超过此值视为劣化
THROUGHPUT_DROP_RATIO = 0.5       # 带宽跌到基线一半以下才算受限；无基线时不参与判定


def _confidence(strength: float, sample_size: int, corroborated: bool = False) -> float:
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
    return round(min(0.99, base * (0.7 + 0.3 * size_factor) * boost), 3)


class TelemetryService:
    def __init__(self): self.fault='normal'; self.tick=0
    def inject(self, fault: str):
        self.fault=fault; STORE.log('experiment', f'fault injected: {fault}', 'warn')
        return {'fault': fault, 'ok': True}
    def sample(self, record: bool=True) -> TelemetrySnapshot:
        self.tick += 1
        if self.fault == 'congestion': snap=TelemetrySnapshot(latency_ms=68, packet_loss=0.018, throughput_mbps=32, alert=True)
        elif self.fault == 'link_down': snap=TelemetrySnapshot(latency_ms=999, packet_loss=1.0, throughput_mbps=0, alert=True)
        elif self.fault == 'guest_spike': snap=TelemetrySnapshot(latency_ms=55, packet_loss=0.008, throughput_mbps=118, alert=True)
        else: snap=TelemetrySnapshot(latency_ms=23+(self.tick%4), packet_loss=0.0002, throughput_mbps=82, alert=False)
        if record:
            STORE.record_telemetry(snap)
        return snap
    def diagnose(self, snapshots=None, baseline_throughput_mbps: float | None = None) -> Diagnosis:
        snapshots=snapshots or STORE.telemetry[-3:]
        if not snapshots: return Diagnosis(type='normal')
        last=snapshots[-1]
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
                             evidence={'packet_loss':loss,'latency_ms':latency},
                             confidence=_confidence(strength, n))
        if loss >= LOSS_DEGRADED:
            return Diagnosis(type='link_down',
                             evidence={'packet_loss':loss,'latency_ms':latency},
                             confidence=_confidence(loss, n))
        # 延迟劣化即可判定拥塞。带宽是佐证不是必要条件——实验台实测：
        # 注入 120ms 延迟不限速时带宽 18.66Mbps，与健康态 21.08 接近，
        # 说明「延迟升高」与「带宽受限」是独立的两件事。
        if latency > LATENCY_DEGRADED_MS:
            ev={'latency_ms':latency}
            strength=min(1.0, (latency - LATENCY_DEGRADED_MS) / LATENCY_DEGRADED_MS)
            corroborated = bool(bw_drop is not None and bw_drop >= THROUGHPUT_DROP_RATIO)
            if corroborated:
                ev['throughput_drop_ratio']=round(bw_drop,3)
            return Diagnosis(type='congestion', evidence=ev,
                             confidence=_confidence(strength, n, corroborated))
        if bw_drop is not None and bw_drop >= THROUGHPUT_DROP_RATIO:
            return Diagnosis(type='anomaly_traffic',
                             evidence={'throughput_drop_ratio':round(bw_drop,3)},
                             confidence=_confidence(bw_drop, n))
        return Diagnosis(type='normal')
    def heal(self, diagnosis: Diagnosis) -> HealingReport:
        before=STORE.telemetry[-1] if STORE.telemetry else self.sample()
        action={'congestion':'启用备用路径并重新下发流表','link_down':'回滚故障链路策略并切换备用链路','anomaly_traffic':'应用访客限速与隔离策略','config_error':'回滚最近配置','normal':'无需动作'}[diagnosis.type]
        self.fault='normal'
        after=self.sample()
        report=HealingReport(action_taken=action,before_snapshot=before,after_snapshot=after,summary=f'{action}；处置后重新观测（{after.source}）：{after.latency_ms}ms')
        STORE.log('healing', report.summary, 'info')
        return report
TELEMETRY=TelemetryService()
