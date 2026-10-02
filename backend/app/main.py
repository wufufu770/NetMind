from __future__ import annotations
import os
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .core import access
from .core import ratelimit
from .core import observability as obs
from .store import STORE
from . import __version__
from .routers import (system, intents, templates_manage, policies, deploy,
                      approvals, topology, telemetry, agents, logs_audit,
                      config, workflows, tools_mcp, reports, audit)

app=FastAPI(title='NetMind API', version=__version__)
_cors=[o.strip() for o in os.getenv('NETMIND_CORS_ORIGINS','http://localhost:5173').split(',') if o.strip()]
# 原来默认 '*' + allow_credentials=True——自相矛盾（浏览器会拒绝），且表达的是
# 「允许任意站点带凭据调我」。默认收紧到本地前端；真要放开由部署方显式配置。
app.add_middleware(CORSMiddleware, allow_origins=_cors,
                   allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

@app.middleware('http')
async def auth_gate(request, call_next):
    d = access.evaluate(request)
    if d.allowed:
        request.state.auth_mode = d.mode
        return await call_next(request)
    return JSONResponse({'error': d.reason, 'auth_mode': d.mode,
                         'hint': '设置 NETMIND_ADMIN_TOKEN 后用 Authorization: Bearer <token>；'
                                 '或设置 NETMIND_ALLOW_ANON_READONLY=true 显式开启匿名只读'},
                        status_code=d.status)


@app.middleware('http')
async def rate_limit(request, call_next):
    # 限流在鉴权之前：未授权的洪水请求同样要挡，不能让它先打到业务逻辑。
    key = access._client_host(request) or 'unknown'
    group = ratelimit.classify(request.method, request.url.path)
    ok, info = ratelimit.allow(key, group)
    if not ok:
        return JSONResponse(
            {'error': 'rate limit exceeded', 'group': info['group'],
             'limit_per_second': info['limit'], 'burst': info['burst']},
            status_code=429, headers={'Retry-After': str(info['retry_after'])})
    return await call_next(request)


@app.middleware('http')
async def observe_requests(request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    dt = time.perf_counter() - t0
    obs.observe('http.request', dt)
    obs.inc('http.requests')
    obs.inc(f'http.status.{response.status_code // 100}xx')
    if response.status_code >= 500:
        obs.inc('http.errors.5xx')
    elif response.status_code >= 400:
        obs.inc('http.errors.4xx')
    response.headers['X-NetMind-Duration-Ms'] = f'{dt * 1000:.1f}'
    return response


@app.get('/healthz', include_in_schema=False)
async def healthz():
    """存活探针。免认证，供容器与负载均衡使用。"""
    return {'status': 'ok', 'version': __version__,
            'uptime_seconds': round(time.time() - obs.STARTED_AT, 2)}


@app.get('/metrics', include_in_schema=False)
async def metrics():
    """自身运行指标。走常规认证——里面是运行数据。"""
    return obs.snapshot()

@app.middleware('http')
async def persist_after_mutations(request, call_next):
    response = await call_next(request)
    if request.method in {'POST','PUT','PATCH','DELETE'} and response.status_code < 500:
        try:
            STORE.mark_dirty()
        except Exception as exc:
            STORE.log('store', f'persist failed: {exc}', 'error')
    return response

STORE.start_autosave()

for module in [system, intents, templates_manage, policies, deploy, approvals,
               topology, telemetry, agents, logs_audit, config, workflows,
               tools_mcp, reports, audit]:
    app.include_router(module.router)
