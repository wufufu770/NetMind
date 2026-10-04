from __future__ import annotations
import os
from uuid import uuid4
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


def _normal_confidence(latency_ms: float, loss: float, sample_size: int,
                       simulated: bool) -> float:
    """「一切正常」的置信度，同样要由可观测状态推导。

    此前这条路径直接返回 `Diagnosis(type='normal')`，吃到 schema 默认的
    confidence=0.9。后果有三层，都实测过：
      · 样本量 1 和样本量 10 给出完全相同的 0.9——「依据变多」不体现在结论上
      · 读数贴着阈值（45ms vs 50ms 门限）和读数极低（1ms）同样给 0.9
      · `sim` 折扣在正常分支完全没生效——模拟数据得出的「一切正常」和真实
        数据一样自信

    这里的判据是「离阈值有多远」：离门限越远、样本越多、数据越真实，
    越有底气说正常。三者缺一不可。
    """
    # 距离最紧的那条阈值越近，越说不出「一切正常」
    latency_margin = max(0.0, LATENCY_DEGRADED_MS - float(latency_ms or 0.0))
    loss_margin = max(0.0, LOSS_DEGRADED - float(loss or 0.0))
    # 延迟是主判据，丢包兜底；取两者中更保守的那个
    strength = min(1.0, latency_margin / LATENCY_DEGRADED_MS,
                   loss_margin / LOSS_DEGRADED if LOSS_DEGRADED else 1.0)
    return _confidence(strength, sample_size, simulated=simulated)


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
        if not snapshots:
            # 一个样本都没有，就没有依据说「正常」。此前这里返回
            # Diagnosis(type='normal')，吃到 schema 默认的 confidence=0.9——
            # 全项目最常见的诊断结论，恰恰是唯一不经过任何推导的那个。
            return Diagnosis(type='normal', confidence=0.0,
                             evidence={'reason': '没有任何遥测样本，无法判定'})
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
        return Diagnosis(type='normal',
                         evidence={'latency_ms': latency, 'packet_loss': loss,
                                   'samples': n},
                         confidence=_normal_confidence(latency, loss, n, sim))
    def heal(self, diagnosis: Diagnosis, *, iface: str | None = None,
             backup: str | None = None,
             bridge: str | None = None) -> HealingReport:
        """自愈：生成真命令 → 过安全门 → 真下发 → 重测 → 必要时回滚。

        此前这里只把 `self.fault` 改回 'normal' 再采一次样，动作是中文描述串，
        不产生任何真实副作用。现在处置是一条真能过白名单的命令，经
        TransactionManager 下发（受危险操作语义门、cookie/路由归属校验、
        回滚保护），下发完**重测**并与处置前对比——改善与否由数据说话。

        报告严格区分四种情况，不含糊：
          · 真下发且指标改善   → success=True, verified=True
          · 干跑/仿真未真下发   → applied=False，明确说没动设备
          · 真下发但设备拒执行 → success=False，设备侧未改变
          · 真下发且没改善     → success=False，**调用 rollback 撤销**；
            撤不回来时（如 congestion 清了原有整形但没记参数）如实说撤不回来，
            并在 rollback 段给出可执行的诊断命令，不拿只读检查冒充回滚
        """
        from .heal_guard import (AttemptCapReached, HealingDisabled, check_attempt,
                                 guard, record_failure, record_success, target_for)
        from .remediation import RemediationUnavailable, build, rollback_info

        before = STORE.telemetry[-1] if STORE.telemetry else self.sample()
        eid = f'heal-{uuid4().hex[:8]}'
        STORE.last_heal_execution = eid

        # 调用方没给目标就按配置兜底；两处都没有则自动处置处于关闭状态。
        # 不猜接口：猜错会把命令下到错误的口上。
        params: dict = {'iface': iface, 'backup': backup, 'bridge': bridge}
        if not iface:
            try:
                params.update(target_for(diagnosis.type))
            except HealingDisabled as off:
                # 「未启用」和「没做」都要落到同一句结论上：设备侧什么都没变。
                # 报告是要被人扫读的，只说「未配置」不足以让人确认没被动过设备。
                rep = HealingReport(
                    action_taken=f'未执行：{off}', before_snapshot=before,
                    after_snapshot=before, success=False, verified=False,
                    improvement={'disabled': str(off), 'target_configured': False},
                    summary=f'{off}；未产生任何设备侧变更')
                STORE.log('healing', rep.summary, 'warn', eid)
                return rep

        try:
            plan = build(diagnosis, iface=params['iface'], backup=params['backup'],
                         bridge=params['bridge'],
                         execution_id=eid)
        except RemediationUnavailable as exc:
            self.fault = 'normal' if diagnosis.type == 'normal' else self.fault
            rep = HealingReport(
                action_taken=f'无需处置：{exc}', before_snapshot=before,
                after_snapshot=before, success=False, verified=False,
                improvement={'no_action': str(exc)},
                summary=f'{exc}；未产生任何设备侧变更')
            STORE.log('healing', rep.summary, 'info', eid)
            return rep

        kind = diagnosis.type
        iface_used = params['iface']
        try:
            prior = guard(STORE, kind, iface_used)
        except AttemptCapReached as cap:
            rep = HealingReport(
                action_taken=f'未执行：{cap}', before_snapshot=before,
                after_snapshot=before, success=False, verified=False,
                improvement={'capped': str(cap), 'target_configured': True,
                             'attempts_before': check_attempt(STORE, kind, iface_used)},
                summary=str(cap))
            STORE.log('healing', rep.summary, 'error', eid)
            return rep

        from .transaction import TRANSACTION
        deploy = TRANSACTION.deploy(eid, plan)
        # 干跑/仿真不算「已下发」——mode 如实带在报告里
        applied = bool(deploy.success) and str(deploy.mode) == 'real'
        after = self.sample()
        lat_before = float(before.latency_ms or 0.0)
        lat_after = float(after.latency_ms or 0.0)
        loss_before = float(before.packet_loss or 0.0)
        loss_after = float(after.packet_loss or 0.0)
        improved = (lat_after <= lat_before * 0.8) or (loss_before - loss_after >= 0.02)

        imp = {
            'planned_commands': [c for p in plan.policies for c in p.commands],
            'executed': [e.model_dump(mode='json') for e in deploy.executed],
            'deploy_success': deploy.success,
            'deploy_mode': deploy.mode,
            # 真正落到设备上的标志。干跑/仿真下即便 deploy.success 为真，
            # 这个也必须是 False——它回答的是「设备被动过没有」。
            'applied': applied,
            'rolled_back': deploy.rolled_back,
            'latency_before_ms': lat_before, 'latency_after_ms': lat_after,
            'loss_before': loss_before, 'loss_after': loss_after,
            'measurement_source': str(after.source),
            'measured': 'real' if str(after.source) in ('real', 'lab') else 'simulated',
            'attempts_before': prior,
        }
        if str(deploy.mode) != 'real':
            why = f'当前是 {deploy.mode} 模式'
            # 干跑没动过设备，不消耗重试预算——那不是「试过一次没成」，
            # 只是没真的做。同样必须写在构造报告之前。
            imp['attempts_before'] = prior
            rep = HealingReport(
                action_taken=imp['planned_commands'][0] if imp['planned_commands'] else '无',
                before_snapshot=before, after_snapshot=after,
                success=False, verified=str(after.source) in ('real', 'lab'),
                improvement=imp,
                summary=(f"处置命令已生成并过安全门，但{why}——"
                         f'**未真的下发到设备**，不报成功'))
        elif not deploy.success:
            # 模式是 real 但下发失败了——这跟「没下发」是两回事，文案不能说混
            failed = [e for e in imp['executed'] if e.get('command') and not e.get('success')]
            detail = '; '.join(f"{e.get('command')} → {str(e.get('output'))[:60]}" for e in failed[:2])
            # 记账必须在构造报告之前：pydantic 构造时会把 improvement 拷走，
            # 之后再往那个 dict 里赋值，报告里看不到。
            imp['attempts'] = record_failure(STORE, kind, iface_used)
            rep = HealingReport(
                action_taken=imp['planned_commands'][0] if imp['planned_commands'] else '无',
                before_snapshot=before, after_snapshot=after,
                success=False, verified=True, improvement=imp,
                summary=(f'**真下发了但设备拒绝执行**：{detail or "命令返回非零"}——'
                         f'设备侧状态未改变，不报成功'))
        else:
            rb = rollback_info(diagnosis.type,
                                {'iface': iface_used, 'backup': params['backup']})
            if not improved:
                # 真下发了但没改善——撤销，别把更糟的状态留在设备上。
                # 能力不足时（congestion 清了原有整形但没记参数）如实说撤不回来，
                # 不拿一条只读的 qdisc show 冒充回滚。
                res = TRANSACTION.rollback(
                    plan, eid,
                    reason=f'post-verify no improvement: {lat_before}->{lat_after}ms')
                imp['attempts'] = record_failure(STORE, kind, iface_used)
                rb.update(attempted=True, rolled_back=res.rolled_back,
                          complete=res.rollback_complete,
                          executed_cmds=[e.model_dump(mode='json') for e in res.executed])
                imp['rollback'] = rb
                verb = ('已回滚' if res.rolled_back and res.rollback_complete
                        else '回滚未完成' if res.rolled_back
                        else '无法自动回滚')
                rep = HealingReport(
                    action_taken=imp['planned_commands'][0] if imp['planned_commands'] else '无',
                    before_snapshot=before, after_snapshot=after,
                    success=False, verified=True, improvement=imp,
                    summary=(f"已下发并重测：{lat_before}→{lat_after}ms，"
                             f'丢包 {loss_before}→{loss_after}（**未改善**），{verb}'
                             f'——{rb["note"]}'))
            else:
                record_success(STORE, kind, iface_used)
                rb.update(attempted=False, rolled_back=False, complete=None)
                imp['rollback'] = rb
                rep = HealingReport(
                    action_taken=imp['planned_commands'][0] if imp['planned_commands'] else '无',
                    before_snapshot=before, after_snapshot=after,
                    success=True, verified=True, improvement=imp,
                    summary=(f"已下发并重测：{lat_before}→{lat_after}ms，"
                             f'丢包 {loss_before}→{loss_after}（已改善）'))
        STORE.log('healing', rep.summary, 'info' if rep.success else 'warn', eid)
        return rep
TELEMETRY=TelemetryService()
