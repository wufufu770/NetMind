from __future__ import annotations
from fastapi import APIRouter, Body
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
