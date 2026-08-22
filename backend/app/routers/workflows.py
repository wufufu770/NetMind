from __future__ import annotations
from fastapi import APIRouter
from ..schemas import WorkflowRunRequest, ToolCallRequest
from ..core.workflow import ORCHESTRATOR
from ..store import STORE

router = APIRouter()

@router.post('/api/workflows/run')
def workflow_run(req: WorkflowRunRequest):
    return ORCHESTRATOR.run_closed_loop(req.intent_text, dry_run=req.dry_run, workflow_id=req.workflow_id)

@router.get('/api/workflows/catalog')
def workflow_catalog():
    return [{'id': w.id, 'name': w.name, 'enabled': w.enabled, 'nodes': w.graph.get('nodes', []), 'edges': w.graph.get('edges', [])} for w in STORE.workflows.values()]

@router.get('/api/workflows/explain/cross-domain')
def explain_cross_domain():
    return {
        'title': '跨域协商',
        'meaning': '当一个意图同时影响校园域、访客域、云域或实验室域时，不让单个策略直接覆盖全网，而是让各域 Agent 提交 proposal/counter-proposal，最后由 Orchestrator 汇总成折中策略。',
        'example': '答辩保障需要提高会议流量优先级，但访客隔离要求禁止访客访问实验室；跨域协商会保留会议服务器临时访问，同时继续限制访客到实验室。',
        'rounds': [{'domain':'campus','proposal':'meeting priority queue=5'}, {'domain':'guest','counter':'keep guest limit 5Mbps'}, {'domain':'lab','constraint':'deny guest to lab'}, {'domain':'orchestrator','final':'priority meeting + scoped guest limit + lab deny'}]
    }

@router.get('/api/cron/presets')
def cron_presets():
    return [
        {'id':'always','label':'始终启用','cron':'* * * * *','description':'每分钟可调度，适合常驻 Agent'},
        {'id':'every_5_min','label':'每 5 分钟','cron':'*/5 * * * *','description':'周期性遥测或日志汇总'},
        {'id':'daily_2am','label':'每天 02:00','cron':'0 2 * * *','description':'备份窗口、低峰期维护'},
        {'id':'workday_8am','label':'工作日 08:00','cron':'0 8 * * 1-5','description':'办公网络预热'},
        {'id':'defense_8pm','label':'每天 20:00','cron':'0 20 * * *','description':'答辩/会议保障场景'},
        {'id':'custom','label':'自定义','cron':'','description':'格式：分 时 日 月 周，例如 30 21 * * 1-5'}
    ]

@router.post('/api/cron/explain')
def cron_explain(payload: dict):
    from ..core.tools_registry import TOOLS
    return TOOLS.call(ToolCallRequest(tool_name='free_cron_explain', arguments={'cron': payload.get('cron','')}, dry_run=True))
