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

@router.get('/api/telemetry/predict-sla')
def telemetry_predict_sla():
    history = STORE.telemetry[-10:] or [TELEMETRY.sample()]
    avg_latency = sum(float(s.latency_ms) for s in history) / max(len(history), 1)
    confidence = max(0.0, min(1.0, 1 - max(avg_latency - 50, 0) / 100))
    return {'achievable': avg_latency <= 50, 'confidence': round(confidence, 2), 'average_latency_ms': round(avg_latency, 2), 'window': len(history)}
