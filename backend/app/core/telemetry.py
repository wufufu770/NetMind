from __future__ import annotations
from ..schemas import TelemetrySnapshot, Diagnosis, HealingReport
from ..store import STORE

class TelemetryService:
    def __init__(self): self.fault='normal'; self.tick=0
    def inject(self, fault: str):
        self.fault=fault; STORE.log('experiment', f'fault injected: {fault}', 'warn')
        return {'fault': fault, 'ok': True}
    def sample(self) -> TelemetrySnapshot:
        self.tick += 1
        if self.fault == 'congestion': snap=TelemetrySnapshot(latency_ms=68, packet_loss=0.018, throughput_mbps=32, alert=True)
        elif self.fault == 'link_down': snap=TelemetrySnapshot(latency_ms=999, packet_loss=1.0, throughput_mbps=0, alert=True)
        elif self.fault == 'guest_spike': snap=TelemetrySnapshot(latency_ms=55, packet_loss=0.008, throughput_mbps=118, alert=True)
        else: snap=TelemetrySnapshot(latency_ms=23+(self.tick%4), packet_loss=0.0002, throughput_mbps=82, alert=False)
        STORE.telemetry.append(snap)
        return snap
    def diagnose(self, snapshots=None) -> Diagnosis:
        snapshots=snapshots or STORE.telemetry[-3:]
        if not snapshots: return Diagnosis(type='normal')
        last=snapshots[-1]
        if last.packet_loss >= .9: return Diagnosis(type='link_down', evidence={'packet_loss':last.packet_loss}, confidence=.98)
        if last.latency_ms > 50 and last.throughput_mbps < 60: return Diagnosis(type='congestion', evidence={'latency_ms':last.latency_ms,'throughput_mbps':last.throughput_mbps}, confidence=.92)
        if last.throughput_mbps > 100: return Diagnosis(type='anomaly_traffic', evidence={'throughput_mbps':last.throughput_mbps}, confidence=.88)
        return Diagnosis(type='normal')
    def heal(self, diagnosis: Diagnosis) -> HealingReport:
        before=STORE.telemetry[-1] if STORE.telemetry else self.sample()
        action={'congestion':'启用备用路径并重新下发流表','link_down':'回滚故障链路策略并切换备用链路','anomaly_traffic':'应用访客限速与隔离策略','config_error':'回滚最近配置','normal':'无需动作'}[diagnosis.type]
        self.fault='normal'
        after=TelemetrySnapshot(latency_ms=23, packet_loss=0.0002, throughput_mbps=82, alert=False)
        STORE.telemetry.append(after)
        report=HealingReport(action_taken=action,before_snapshot=before,after_snapshot=after,summary=f'{action}，指标恢复至 {after.latency_ms}ms')
        STORE.log('healing', report.summary, 'info')
        return report
TELEMETRY=TelemetryService()
