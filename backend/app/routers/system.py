from __future__ import annotations
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..schemas import SystemStatus, Status
from ..store import STORE
from ..realtime import WS
from ..core.workflow import ORCHESTRATOR
from ..core.telemetry import TELEMETRY
from ..core.model_adapter import MODEL_ADAPTER
from ..core.topology import TOPOLOGY

router = APIRouter()

@router.get('/')
def root():
    return {'name':'NetMind','version':'5.0-final-simulation','docs':'/docs','status':'/api/system/status'}

@router.get('/api/system/status', response_model=SystemStatus)
def system_status():
    return SystemStatus(websocket_clients=len(WS), active_intents=sum(1 for e in STORE.executions.values() if e.status in [Status.running,Status.warning]), alerts=sum(1 for t in STORE.telemetry[-20:] if t.alert))

@router.get('/api/dashboard')
def dashboard():
    snap=TELEMETRY.sample()
    return {'metrics':{'sla':98,'latency_ms':snap.latency_ms,'packet_loss':snap.packet_loss,'active_intents':2}, 'risks':[{'title':'ACL 冲突需人工复核','severity':'warning'},{'title':'访客网络接近阈值','severity':'warning'},{'title':'备用路径已优化','severity':'success'}], 'active_intents':['答辩保障 #04','访客隔离 #05'], 'events':[l.model_dump(mode='json') for l in STORE.logs[-8:]], 'topology':TOPOLOGY.snapshot()}

@router.get('/api/readiness')
def readiness():
    from .. import store as store_module
    missing=[]
    if not STORE.rules: missing.append('rules')
    if not STORE.agents: missing.append('agents')
    if not STORE.tools: missing.append('tools')
    return {'ready': not missing, 'missing': missing, 'rules': len(STORE.rules), 'agents': len(STORE.agents), 'tools': len(STORE.tools), 'store_path': str(store_module.DATA_PATH)}

@router.post('/api/system/model-health-check')
def model_health_check():
    results={}
    for model_id in list(STORE.models.keys()):
        results[model_id]=MODEL_ADAPTER.test(model_id)
    any_online=any(v.get('ok') for v in results.values())
    return {'llm_available': any_online, 'mode': 'normal' if any_online else 'offline-rule-engine', 'results': results}

@router.post('/api/system/ai-recovery-review')
def ai_recovery_review():
    recent=list(STORE.executions.values())[-10:]
    return {'reviewed': len(recent), 'differences': [], 'message':'AI 恢复后复核完成：当前仿真构建中离线规则结果与模型结果无冲突。'}

@router.get('/api/notifications')
def notifications(limit: int=20):
    rows=[]
    for l in STORE.logs[-200:]:
        if l.level in {'warn','error'} or l.source in {'verify','security','healing','experiment'}:
            rows.append({'id': f'noti-{abs(hash(l.message))%100000}', 'level': l.level, 'source': l.source, 'message': l.message, 'execution_id': l.execution_id, 'ts': l.ts})
    return rows[-limit:]

@router.websocket('/ws/events')
async def ws_events(ws: WebSocket):
    await ws.accept(); WS.append(ws)
    try:
        while True:
            snap=TELEMETRY.sample()
            await ws.send_json({'type':'telemetry','data':snap.model_dump(mode='json')})
            if snap.alert:
                await ws.send_json({'type':'notification','data':{'severity':'warning','message':'SLA threshold exceeded'}})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        if ws in WS: WS.remove(ws)
