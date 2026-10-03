from __future__ import annotations
from fastapi import APIRouter, Body, HTTPException
from ..schemas import TelemetrySnapshot, Diagnosis, HealingReport
from ..store import STORE
from ..core.telemetry import TELEMETRY

router = APIRouter()

@router.get('/api/telemetry/latest', response_model=TelemetrySnapshot)
def telemetry_latest(): return TELEMETRY.sample()

@router.get('/api/telemetry/history')
def telemetry_history(limit: int=50): return STORE.telemetry[-limit:]

@router.post('/api/experiment/fault')
def inject_fault(kind: str = Body(..., embed=True)): return TELEMETRY.inject(kind)

@router.post('/api/telemetry/diagnose', response_model=Diagnosis)
def diagnose(): return TELEMETRY.diagnose()

@router.post('/api/telemetry/heal', response_model=HealingReport)
def heal(): return TELEMETRY.heal(TELEMETRY.diagnose())

@router.get('/api/vendors')
def vendors():
    """厂商能力矩阵。每条都标验证等级，别让「支持某厂商」只是一句声明。"""
    from ..diagnose.vendor_matrix import matrix, summary
    return {'summary': summary(), 'vendors': matrix()}


@router.get('/api/vendors.md')
def vendors_markdown():
    from ..diagnose.vendor_matrix import as_markdown
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(as_markdown())


@router.post('/api/lab/loop', response_model=HealingReport)
def lab_loop(baseline_throughput_mbps: float | None = Body(None, embed=True),
             count: int = Body(10, embed=True)):
    """在真实验台上跑完整闭环：真探测 → 真诊断 → 真处置 → 真重测 → 验证。

    与 /api/telemetry/heal 的区别：后者走模拟路径，verified 恒为 False；
    这里 success 只能由实测前后对比推出。实验台没起时如实报错，不降级成模拟。
    """
    from ..diagnose.lab_adapter import run_lab_loop
    try:
        return run_lab_loop(baseline_throughput_mbps=baseline_throughput_mbps, count=count)
    except Exception as exc:
        raise HTTPException(503, detail=f'实验台不可用，未降级为模拟: {type(exc).__name__}: {exc}')

@router.get('/api/telemetry/anomaly')
def telemetry_anomaly(limit: int=12):
    rows=[]
    history = STORE.telemetry[-limit:] or [TELEMETRY.sample() for _ in range(min(limit, 3))]
    for snap in history:
        rows.append({'ts': snap.ts, 'latency_ms': snap.latency_ms, 'packet_loss': snap.packet_loss, 'severity': 'warning' if snap.alert else 'normal', 'reason': 'SLA threshold exceeded' if snap.alert else 'within baseline'})
    return rows

# 没有约定目标时不做可行性判定。硬编一个 50ms 门槛等于替用户决定了
# 「什么叫达标」——那不是推断，是替人做决定。
SLA_ASSESSABLE = 'assessed'
SLA_NO_TARGET = 'no-target-provided'

@router.post('/api/telemetry/predict-sla')
def telemetry_predict_sla(payload: dict = Body(default_factory=dict)):
    """按**调用方给的目标**判定历史观测是否达标。

    原实现是 GET 且无请求体，把门槛写死成 50ms，而前端 POST 传了完整目标
    （`sla: {latency_ms, packet_loss, bandwidth_mbps}`）却从未被读取——两边
    对不上，界面上这个功能实际是坏的：POST 直接 405，GET 返回的字段名
    （`achievable`）和前端读的（`feasible`）也不一致。

    判定依据是历史遥测的实测均值，结论里同时给出「用的哪个目标」，
    避免读的人以为这是随便挑的阈值。
    """
    sla = payload.get('sla') or {}
    target_latency = sla.get('latency_ms')
    target_loss = sla.get('packet_loss')

    history = STORE.telemetry[-10:] or [TELEMETRY.sample()]
    avg_latency = sum(float(s.latency_ms or 0.0) for s in history) / max(len(history), 1)
    losses = [float(s.packet_loss or 0.0) for s in history]
    avg_loss = sum(losses) / max(len(losses), 1)
    sources = sorted({str(getattr(s, 'source', '')) for s in history})

    base = {
        'average_latency_ms': round(avg_latency, 2),
        'average_packet_loss': round(avg_loss, 5),
        'window': len(history),
        'measurement_sources': sources,
        'target_used': {'latency_ms': target_latency, 'packet_loss': target_loss},
    }

    if target_latency is None and target_loss is None:
        # 没有目标就没有「可行/不可行」——只如实给实测值
        return {**base, 'verdict': SLA_NO_TARGET,
                'feasible': None,
                'message': '未提供 SLA 目标，无法判定可行性；此处只返回实测均值'}

    checks = []
    if target_latency is not None:
        checks.append(('latency_ms', avg_latency, float(target_latency), 'ms'))
    if target_loss is not None:
        checks.append(('packet_loss', avg_loss, float(target_loss), ''))
    breaches = [{'metric': m, 'observed': round(obs, 5), 'target': tgt, 'unit': unit}
                for m, obs, tgt, unit in checks if obs > tgt]
    return {**base, 'verdict': SLA_ASSESSABLE, 'feasible': not breaches,
            'breaches': breaches, 'checks': [
                {'metric': m, 'observed': round(obs, 5), 'target': tgt,
                 'unit': unit, 'pass': obs <= tgt} for m, obs, tgt, unit in checks],
            'message': ('历史均值满足所给目标' if not breaches
                        else f'{len(breaches)} 项超出所给目标')}
