#!/usr/bin/env python3
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
checks=[]

def add(name, ok, detail=''):
    checks.append({'name':name,'ok':bool(ok),'detail':detail})

required=[
    'backend/app/main.py','backend/app/schemas.py','backend/app/store.py','backend/app/core/rule_engine.py',
    'backend/app/core/security.py','backend/app/core/verification.py','backend/app/core/transaction.py',
    'backend/app/core/telemetry.py','backend/app/core/report.py','frontend/src/App.jsx','backend/app/cli.py',
    'docker-compose.yml','README.md',
    'backend/app/core/langgraph_compat.py','backend/app/core/mcp_protocol.py','backend/app/core/chat_agent.py',
    'backend/app/core/tool_sequence.py','backend/app/core/config_extras.py',
    'backend/app/core/report_renderer.py',
    'backend/tests/test_v4_ten_round_completion.py'
]
for rel in required:
    add(f'file:{rel}', (ROOT/rel).exists())

sys.path.insert(0, str(ROOT/'backend'))
try:
    from app.main import app
    add('app_import', True)
    routes={r.path for r in app.routes}
    for critical in ['/api/intent/submit','/api/policy/conflict-matrix','/api/deploy/{execution_id}','/api/config/export']:
        add(f'route:{critical}', critical in routes)
except Exception as exc:
    add('app_import', False, str(exc))

add('safe_default_driver', 'NETMIND_ENABLE_REAL_COMMANDS=false' in (ROOT/'.env.example').read_text(encoding='utf-8'))
add('docker_compose', 'backend:' in (ROOT/'docker-compose.yml').read_text(encoding='utf-8'))

print(json.dumps({'ok': all(c['ok'] for c in checks), 'checks': checks}, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(c['ok'] for c in checks) else 1)
