from __future__ import annotations
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .store import STORE
from .routers import (system, intents, templates_manage, policies, deploy,
                      approvals, topology, telemetry, agents, logs_audit,
                      config, workflows, tools_mcp, reports)

app=FastAPI(title='NetMind Complete API', version='4.0-complete')
_cors=[o.strip() for o in os.getenv('NETMIND_CORS_ORIGINS','*').split(',') if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors, allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

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
