from __future__ import annotations
from fastapi import APIRouter
from ..schemas import AuditSummary
from ..store import STORE

router = APIRouter()

@router.get('/api/logs')
def logs(source: str|None=None, level: str|None=None, limit: int=100):
    rows=STORE.logs
    if source: rows=[r for r in rows if r.source==source]
    if level: rows=[r for r in rows if r.level==level]
    return rows[-limit:]

@router.get('/api/audit/summary', response_model=AuditSummary)
def audit_summary():
    return AuditSummary(
        executions=len(STORE.executions),
        logs=len(STORE.logs),
        security_events=len([l for l in STORE.logs if l.source in {'security','deploy'} or l.level=='error']),
        approvals_pending=len([a for a in STORE.approvals.values() if a.status=='pending']),
        healing_events=len([e for e in STORE.executions.values() if e.healing is not None]),
    )

@router.get('/api/logs/search')
def search_logs(q: str='', source: str|None=None, level: str|None=None, limit: int=100):
    rows=STORE.logs
    if source: rows=[r for r in rows if r.source==source]
    if level: rows=[r for r in rows if r.level==level]
    if q: rows=[r for r in rows if q.lower() in r.message.lower() or q.lower() in str(r.data).lower()]
    return rows[-limit:]
