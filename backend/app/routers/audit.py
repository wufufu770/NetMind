from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, HTTPException
from ..core.audit import run_audit, render_markdown, CHECKS, ReadonlyViolation
from ..store import STORE

router = APIRouter()

AUDIT_DIR = Path(__file__).resolve().parents[2] / 'data' / 'audit'


@router.get('/api/audit/checks')
def audit_checks():
    return [{'id': c['id'], 'title': c['title'], 'commands': c['commands']} for c in CHECKS]


@router.post('/api/audit/run')
def audit_run(payload: dict | None = None):
    payload = payload or {}
    try:
        report = run_audit(mode=payload.get('mode'), note=payload.get('note'))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except ReadonlyViolation as exc:
        raise HTTPException(400, str(exc))
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = AUDIT_DIR / f"{report['audit_id']}.md"
    path.write_text(render_markdown(report), encoding='utf-8')
    STORE.mark_dirty()
    return {**report, 'report_path': str(path.relative_to(AUDIT_DIR.parents[2]))}


@router.get('/api/audit/{audit_id}/report.md')
def audit_report_md(audit_id: str):
    from fastapi import Response
    import re
    if not re.match(r'^audit-[0-9]{8}-[0-9]{6}$', audit_id):
        raise HTTPException(400, 'invalid audit id')
    path = AUDIT_DIR / f'{audit_id}.md'
    if not path.exists():
        raise HTTPException(404, 'report not found')
    return Response(path.read_text(encoding='utf-8'), media_type='text/markdown')
