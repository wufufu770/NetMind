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
    'backend/tests/test_langgraph_mcp_chat_config.py'
]
for rel in required:
    add(f'file:{rel}', (ROOT/rel).exists())

sys.path.insert(0, str(ROOT/'backend'))
try:
    from app.main import app
    add('app_import', True)
    # FastAPI 0.142 起 include_router 产出 _IncludedRouter 包装对象：既没有 .path
    # 也没有 .routes，真实路由藏在 .original_router.routes 里（更早的版本还有
    # .routes 或 Mount.app.routes 两种形态）。原实现 {r.path for r in app.routes}
    # 在新版上直接抛 AttributeError。逐个对象探测，逐层下钻。
    DESCENT_ATTRS = ('routes', 'original_router', 'app')

    def collect_paths(node, seen=None):
        seen = seen if seen is not None else set()
        if id(node) in seen:
            return set()
        seen.add(id(node))
        found = set()
        for r in (getattr(node, 'routes', None) or []):
            p = getattr(r, 'path', None)
            if isinstance(p, str):
                found.add(p)
            found |= collect_paths(r, seen)          # 继续下钻（Mount 之下还有路由）
        for attr in DESCENT_ATTRS[1:]:
            child = getattr(node, attr, None)
            if child is not None and child is not node:
                found |= collect_paths(child, seen)
        return found

    routes = collect_paths(app)
    for critical in ['/api/intent/submit','/api/policy/conflict-matrix','/api/deploy/{execution_id}','/api/config/export']:
        add(f'route:{critical}', critical in routes,
            '' if critical in routes else f'未在 {len(routes)} 条路由中找到；实际含 /api/ 的: '
                                          + ', '.join(sorted(x for x in routes if x.startswith('/api'))[:8]))
except Exception as exc:
    add('app_import', False, f'{type(exc).__name__}: {exc}')

add('safe_default_driver', 'NETMIND_ENABLE_REAL_COMMANDS=false' in (ROOT/'.env.example').read_text(encoding='utf-8'))
add('docker_compose', 'backend:' in (ROOT/'docker-compose.yml').read_text(encoding='utf-8'))

print(json.dumps({'ok': all(c['ok'] for c in checks), 'checks': checks}, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(c['ok'] for c in checks) else 1)
