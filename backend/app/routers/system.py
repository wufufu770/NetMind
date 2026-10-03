from __future__ import annotations
import asyncio
import os
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
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
    from .. import __version__
    return {'name':'NetMind','version':__version__,'docs':'/docs','status':'/api/system/status'}

@router.get('/api/system/status', response_model=SystemStatus)
def system_status(request: Request):
    """运行状态。此前 healthy / driver / model_online 从来没被计算过，
    全部吃 schema 默认值——于是恒返回 healthy=true、driver=simulation、
    model_online=true。探活与运维看的正是这个接口。

    现在四个字段各自有出处：
      · driver         取实际配置的驱动名
      · model_online   走真健康检查，而不是假定模型可用
      · healthy        取决于遥测来源：数据源不真实时不能报「健康」
      · auth_mode      供前端识别调用者档位，隐藏只读身份用不上的写操作
    """
    from ..core.model_adapter import MODEL_ADAPTER as _MA
    driver = os.getenv('NETMIND_DRIVER', 'simulation')
    online = False
    for model_id in list(STORE.models):
        try:
            if _MA.test(model_id).get('ok'):
                online = True
                break
        except Exception:
            continue
    last = STORE.telemetry[-1] if STORE.telemetry else None
    src = str(getattr(last, 'source', '') or '')
    return SystemStatus(
        healthy=bool(src in ('real', 'lab', 'simulated')) if last else False,
        driver=driver,
        model_online=online,
        websocket_clients=len(WS),
        active_intents=sum(1 for e in STORE.executions.values()
                           if e.status in [Status.running, Status.warning]),
        alerts=sum(1 for t in STORE.telemetry[-20:] if t.alert),
        auth_mode=str(getattr(request.state, 'auth_mode', 'unknown')),
        telemetry_source=src,
    )

@router.get('/api/dashboard')
def dashboard():
    # 数字全部由真实状态推出，推不出的返回 null 并带原因（见 core/dashboard.py）。
    # 此前这里是写死的 sla:98 / active_intents:2 和三条固定风险文案，读者
    # 无从判断这些数字是测出来的还是编的。
    from ..core.dashboard import build_dashboard
    return build_dashboard(executions=STORE.executions.values(), telemetry=STORE.telemetry,
                           logs=STORE.logs, topology=TOPOLOGY.snapshot())

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
    """复核「模型恢复后结果与离线规则是否冲突」。

    原实现直接返回 `differences: []` 和一句「复核完成，无冲突」——它什么都没
    比较，那句话因此是编的。现在真跑一遍规则引擎再比；引擎跑不了就如实说跑不了。
    """
    from ..core.workflow import ORCHESTRATOR
    recent = [e for e in list(STORE.executions.values())[-10:] if getattr(e, 'intent_text', '')]
    compared, differences, undecidable = [], [], []
    for e in recent:
        try:
            rederived = ORCHESTRATOR.parse_intent_with_agent(e.intent_text)
        except Exception as exc:
            undecidable.append({'execution_id': e.execution_id,
                                'reason': f'{type(exc).__name__}: {str(exc)[:80]}'})
            continue
        before = getattr(e.intent, 'model_dump', lambda: None)()
        after = rederived[0].model_dump() if hasattr(rederived, '__getitem__') else None
        compared.append(e.execution_id)
        if before and after and before != after:
            differences.append({'execution_id': e.execution_id,
                                'recorded': before, 'rederived': after})
    verdict = ('differences-found' if differences
               else 'no-difference' if compared and not undecidable
               else 'indeterminate' if undecidable or not compared
               else 'partial')
    return {
        'reviewed': len(recent),
        'compared': len(compared),
        'differences': differences,
        'undecidable': undecidable,
        'verdict': verdict,
        'message': {
            'differences-found': f'发现 {len(differences)} 处结果不一致，需人工复核',
            'no-difference': f'逐条重跑 {len(compared)} 个意图，规则输出与记录一致',
            'partial': f'比对 {len(compared)} 条，{len(undecidable)} 条无法判定——'
                       f'未比对的部分不算「无冲突」',
            'indeterminate': '无可比对的执行记录，复核未进行',
        }[verdict],
    }


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
    # 用 finally 而不是只捕 WebSocketDisconnect：原来只捕那一种异常，
    # 发送失败或 TELEMETRY.sample() 抛错时控制流直接抛出函数，ws 永远留在
    # WS 列表里。长跑进程里客户端反复重连，列表只增不减——
    # 而 /api/system/status 正是拿 len(WS) 当「在线客户端数」报的。
    try:
        while True:
            snap=TELEMETRY.sample()
            await ws.send_json({'type':'telemetry','data':snap.model_dump(mode='json')})
            if snap.alert:
                await ws.send_json({'type':'notification','data':{'severity':'warning','message':'telemetry alert: SLA threshold exceeded'}})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        if ws in WS:
            WS.remove(ws)
