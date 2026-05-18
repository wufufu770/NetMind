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
    'backend/app/core/telemetry.py','backend/app/core/report.py','frontend/src/App.jsx','cli/netmind.py',
    'docker-compose.yml','README.md','docs/FEATURE_MATRIX.md',
    # v4 ten-round non-environment completion modules
    'backend/app/core/langgraph_compat.py','backend/app/core/mcp_protocol.py','backend/app/core/chat_agent.py',
    'backend/app/core/tool_sequence.py','backend/app/core/repository_status.py','backend/app/core/config_extras.py',
    'backend/app/core/report_renderer.py','docs/TEN_ROUND_COMPLETION_REPORT.md',
    'backend/tests/test_v4_ten_round_completion.py','frontend/src/services/api.ts','frontend/src/types/index.ts'
]
for rel in required:
    add(f'file:{rel}', (ROOT/rel).exists())

# Import feature matrix directly to validate semantic status, not just text count.
sys.path.insert(0, str(ROOT/'backend'))
try:
    from app.core.feature_matrix import feature_matrix
    fm=feature_matrix()
    non_env_incomplete=[f for f in fm['items'] if f['status']!='implemented' and not f.get('external_dependency')]
    add('feature_matrix_66', fm['total']>=66, f"count={fm['total']}")
    add('non_environment_100_percent', not non_env_incomplete, json.dumps(non_env_incomplete, ensure_ascii=False))
    add('external_dependency_isolated', fm['external_dependency'] <= 10, f"external_dependency={fm['external_dependency']}")
except Exception as exc:
    add('feature_matrix_import', False, str(exc))

add('safe_default_driver', 'NETMIND_ENABLE_REAL_COMMANDS=false' in (ROOT/'.env.example').read_text(encoding='utf-8'))
add('docker_compose', 'backend:' in (ROOT/'docker-compose.yml').read_text(encoding='utf-8'))

print(json.dumps({'ok': all(c['ok'] for c in checks), 'checks': checks}, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(c['ok'] for c in checks) else 1)
