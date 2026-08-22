from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .store import STORE
from . import __version__
from .routers import (system, intents, templates_manage, policies, deploy,
                      approvals, topology, telemetry, agents, logs_audit,
                      config, workflows, tools_mcp, reports)

app=FastAPI(title='NetMind API', version=__version__)
_cors=[o.strip() for o in os.getenv('NETMIND_CORS_ORIGINS','*').split(',') if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

@app.middleware('http')
async def auth_gate(request, call_next):
    token=os.getenv('NETMIND_ADMIN_TOKEN','').strip()
    if token and request.method not in {'GET','HEAD','OPTIONS'}:
        supplied=request.headers.get('authorization','')
        if not (supplied.startswith('Bearer ') and supplied[7:] == token):
            return JSONResponse({'error':'unauthorized'}, status_code=401)
    return await call_next(request)

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
               tools_mcp, reports]:
    app.include_router(module.router)
