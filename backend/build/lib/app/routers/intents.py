from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body
from ..schemas import IntentRequest, IntentDSL, Execution
from ..store import STORE
from ..core.workflow import ORCHESTRATOR
from ..core.rule_engine import RULE_ENGINE
from .common import get_execution

router = APIRouter()

@router.post('/api/intent/parse', response_model=IntentDSL)
def parse_intent(req: IntentRequest):
    intent, meta = ORCHESTRATOR.parse_intent_with_agent(req.text)
    return intent

@router.post('/api/intent/submit', response_model=Execution)
def submit_intent(req: IntentRequest): return ORCHESTRATOR.run_closed_loop(req.text, dry_run=req.dry_run, workflow_id=req.workflow_id)

@router.get('/api/templates')
def templates(): return STORE.templates

@router.post('/api/templates/{template_id}')
def save_template(template_id: str, text: str = Body(..., embed=True)):
    STORE.templates[template_id]=text; return {'ok':True,'template_id':template_id}

@router.get('/api/executions')
def list_executions(): return list(STORE.executions.values())[-50:]

@router.get('/api/executions/{execution_id}', response_model=Execution)
def get_execution_route(execution_id: str): return get_execution(execution_id)

@router.get('/api/executions/{execution_id}/replay')
def replay(execution_id: str):
    ex=get_execution(execution_id)
    return {'execution_id':execution_id,'timeline':[{'agent':s.agent,'status':s.status,'duration_ms':s.duration_ms,'output':s.output} for s in ex.steps]}

@router.get('/api/executions/{execution_id}/tool-sequence')
def execution_tool_sequence(execution_id: str):
    from ..core.tool_sequence import TOOL_SEQUENCE
    return TOOL_SEQUENCE.from_execution(get_execution(execution_id))

@router.post('/api/experiment/scenario/{name}')
def run_scenario(name: str):
    scenarios={
        'defense':'今晚8点保障答辩视频会议，教师终端到会议服务器延迟低于50ms，访客网络限速5Mbps',
        'guest':'访客网络限速5Mbps，并禁止访问实验室服务器',
        'lab':'实验室网络隔离，只允许教师终端访问实验服务器',
        'backup':'凌晨2点到4点保障数据库备份链路，带宽不低于50Mbps'
    }
    if name not in scenarios: raise HTTPException(404,'scenario not found')
    return ORCHESTRATOR.run_closed_loop(scenarios[name], workflow_id='default')

@router.post('/api/intent/resolve-ambiguity')
def resolve_ambiguity(req: IntentRequest):
    text=req.text
    candidates=[]
    if '保障' in text and not any(k in text for k in ['会议','答辩','直播','VoIP','备份']):
        candidates=['video_meeting','live_stream','voip','backup']
    if '隔离' in text and not any(k in text for k in ['访客','实验室','财务','IoT']):
        candidates=['lab_isolation','guest_limiting','finance_isolation','iot_isolation']
    intent=RULE_ENGINE.parse_intent(text)
    intent.ambiguous=bool(candidates)
    intent.candidates=candidates
    return intent

@router.post('/api/intent/compile')
def compile_intent(req: IntentRequest):
    intent, meta = ORCHESTRATOR.parse_intent_with_agent(req.text)
    issues = []
    if not intent.target.src or not intent.target.dst:
        issues.append({'field':'target', 'message':'source and destination should be provided'})
    if intent.sla.latency_ms is not None and intent.sla.latency_ms <= 0:
        issues.append({'field':'sla.latency_ms', 'message':'latency must be positive'})
    return {
        'dsl': intent.model_dump(mode='json'),
        'validation': {'valid': not issues, 'issues': issues, 'meta': meta},
        'workflow_id': req.workflow_id,
    }

@router.post('/api/templates/suggest')
def suggest_template(req: IntentRequest):
    intent=RULE_ENGINE.parse_intent(req.text)
    similar=[]
    for key, text in STORE.templates.items():
        if intent.business == RULE_ENGINE.infer_business(text):
            similar.append({'template_id':key, 'text':text})
    return {'business': intent.business, 'should_save': len(similar) < 1, 'similar_templates': similar[:5]}

@router.post('/api/template-suggestions')
def template_suggestions(req: IntentRequest):
    return suggest_template(req)
