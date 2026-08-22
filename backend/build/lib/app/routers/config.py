from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import PlainTextResponse
from ..schemas import ThemeConfig, ModelConfig, AgentConfig, Rule, ToolConfig, WorkflowConfig, CredentialConfig, IntentDSL
from ..store import STORE
from ..core.workflow import ORCHESTRATOR
from ..core.rule_engine import RULE_ENGINE
from ..core.model_adapter import MODEL_ADAPTER

router = APIRouter()

def config_export():
    return {'models':STORE.models,'agents':STORE.agents,'rules':STORE.rules,'tools':STORE.tools,'workflows':STORE.workflows,'theme':STORE.theme,'mcp_servers':STORE.mcp_servers}

@router.get('/api/config/export')
def config_export_route(): return config_export()

@router.post('/api/config/import')
def config_import(payload: dict):
    if 'theme' in payload: STORE.theme=ThemeConfig(**payload['theme'])
    return {'ok':True,'imported':list(payload.keys())}

@router.get('/api/config/models')
def models(): return list(STORE.models.values())

@router.get('/api/config/models/presets')
def model_presets():
    return [
        {'id':'deepseek','region':'国内','name':'DeepSeek','base_url':'https://api.deepseek.com/v1','models':['deepseek-chat','deepseek-reasoner'],'default_model':'deepseek-chat','context_window':'64K','supports_thinking':True,'api_style':'openai-compatible'},
        {'id':'qwen','region':'国内','name':'阿里百炼 Qwen','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','models':['qwen-plus','qwen-turbo'],'default_model':'qwen-plus','context_window':'128K','supports_thinking':True,'api_style':'openai-compatible'},
        {'id':'openai','region':'国际','name':'OpenAI Compatible','base_url':'https://api.openai.com/v1','models':['gpt-4o','gpt-4o-mini'],'default_model':'gpt-4o-mini','context_window':'128K','supports_thinking':True,'api_style':'openai-compatible'},
        {'id':'ollama','region':'本地','name':'Ollama 本地','base_url':'http://localhost:11434/v1','models':['llama3.1','qwen2.5'],'default_model':'llama3.1','context_window':'local','supports_thinking':False,'api_style':'openai-compatible'},
        {'id':'custom','region':'其他','name':'自定义兼容接口','base_url':'','models':[],'default_model':'','context_window':'custom','supports_thinking':False,'api_style':'openai-compatible'},
    ]

@router.get('/api/config/models/call-history')
def model_call_history(limit: int=50):
    return MODEL_ADAPTER.call_history[-limit:]

@router.post('/api/config/models')
def upsert_model(model: ModelConfig): STORE.models[model.id]=model; return model

@router.post('/api/config/models/test')
def test_model(model_id: str = Body(..., embed=True)): return MODEL_ADAPTER.test(model_id)

@router.delete('/api/config/models/{model_id}')
def delete_model(model_id: str):
    if model_id == 'mock': raise HTTPException(409, 'mock model cannot be deleted')
    existed = model_id in STORE.models
    STORE.models.pop(model_id, None)
    return {'ok': True, 'deleted': model_id, 'existed': existed}

@router.post('/api/config/models/{model_id}/bind-agent/{agent_name}')
def bind_model_to_agent(model_id: str, agent_name: str):
    if model_id not in STORE.models: raise HTTPException(404, 'model not found')
    if agent_name not in STORE.agents: raise HTTPException(404, 'agent not found')
    STORE.agents[agent_name].model_id=model_id
    return STORE.agents[agent_name]

@router.get('/api/config/agents')
def agent_configs(): return list(STORE.agents.values())

@router.get('/api/config/agents/prompts/recommended')
def recommended_agent_prompts():
    return {name: agent.prompt for name, agent in STORE.agents.items()}

@router.get('/api/config/agents/{agent_name}/schedule')
def get_agent_schedule(agent_name: str):
    if agent_name not in STORE.agents: raise HTTPException(404,'agent not found')
    return STORE.agent_schedules.get(agent_name, {'agent':agent_name, 'enabled':True, 'active_schedule':'always'})

@router.put('/api/config/agents/{agent_name}/schedule')
def put_agent_schedule(agent_name: str, payload: dict):
    if agent_name not in STORE.agents: raise HTTPException(404,'agent not found')
    row={'agent':agent_name, 'enabled': bool(payload.get('enabled', True)), 'active_schedule': payload.get('active_schedule','always')}
    STORE.agent_schedules[agent_name]=row
    STORE.mark_dirty()
    return row

@router.delete('/api/config/agents/{agent_name}')
def delete_agent(agent_name: str):
    if agent_name in {'OrchestratorAgent','IntentAgent','PlannerAgent','VerifierAgent','DeployAgent','TelemetryAgent','DiagnosisAgent','HealingAgent'}:
        raise HTTPException(409, 'core agent cannot be deleted; disable it or create a custom workflow without it')
    existed = agent_name in STORE.agents
    STORE.agents.pop(agent_name, None)
    return {'ok': True, 'deleted': agent_name, 'existed': existed}

@router.post('/api/config/agents')
def upsert_agent(agent: AgentConfig): STORE.agents[agent.name]=agent; return agent

@router.get('/api/config/rules')
def rules(): return list(STORE.rules.values())

@router.post('/api/config/rules')
def upsert_rule(rule: Rule): STORE.rules[rule.name]=rule; return rule

@router.post('/api/config/rules/test')
def test_rule(intent: IntentDSL):
    ps, meta = ORCHESTRATOR.plan_with_agent(intent)
    return {'matches':RULE_ENGINE.match(intent), 'policy_set':ps, 'planner_meta':meta}

@router.get('/api/config/tools')
def tools(): return list(STORE.tools.values())

@router.post('/api/config/tools')
def upsert_tool(tool: ToolConfig): STORE.tools[tool.name]=tool; return tool

@router.get('/api/config/workflows')
def workflows(): return list(STORE.workflows.values())

@router.delete('/api/config/workflows/{workflow_id}')
def delete_workflow(workflow_id: str):
    if workflow_id == 'default': raise HTTPException(409, 'default workflow cannot be deleted')
    existed = workflow_id in STORE.workflows
    STORE.workflows.pop(workflow_id, None)
    return {'ok': True, 'deleted': workflow_id, 'existed': existed}

@router.post('/api/config/workflows')
def upsert_workflow(w: WorkflowConfig): STORE.workflows[w.id]=w; return w

@router.get('/api/config/theme', response_model=ThemeConfig)
def theme(): return STORE.theme

@router.post('/api/config/theme')
def update_theme(t: ThemeConfig): STORE.theme=t; return t

@router.get('/api/config/mcp-servers')
def mcp_servers(): return STORE.mcp_servers

@router.post('/api/config/mcp-servers/{name}')
def upsert_mcp(name: str, payload: dict): STORE.mcp_servers[name]=payload; return {'ok':True,'name':name}

@router.post('/api/config/reset-runtime')
def reset_runtime():
    STORE.reset_runtime(); return {'ok': True}

@router.get('/api/config/security')
def get_security_config():
    from ..core.config_extras import get_security_config as _get
    return _get()

@router.put('/api/config/security')
def put_security_config(payload: dict):
    from ..core.config_extras import update_security
    return update_security(payload)

@router.get('/api/config/fonts')
def get_font_config():
    from ..core.config_extras import FONT_CONFIG
    return FONT_CONFIG

@router.put('/api/config/fonts')
def put_font_config(payload: dict):
    from ..core.config_extras import update_fonts
    return update_fonts(payload)

@router.get('/api/store/snapshot')
def store_snapshot():
    return STORE.to_json()

@router.post('/api/store/restore')
def store_restore(payload: dict):
    if 'templates' in payload and isinstance(payload['templates'], dict): STORE.templates.update(payload['templates'])
    if 'theme' in payload: STORE.theme=ThemeConfig(**payload['theme'])
    if 'models' in payload: STORE.models.update({k: ModelConfig(**v) for k,v in payload['models'].items()})
    if 'agents' in payload: STORE.agents.update({k: AgentConfig(**v) for k,v in payload['agents'].items()})
    if 'rules' in payload: STORE.rules.update({k: Rule(**v) for k,v in payload['rules'].items()})
    if 'tools' in payload: STORE.tools.update({k: ToolConfig(**v) for k,v in payload['tools'].items()})
    STORE.save()
    return {'ok': True, 'restored_keys': list(payload.keys())}

@router.post('/api/config/validate')
def config_validate(payload: dict|None=None):
    data=payload or config_export()
    issues=[]
    models=data.get('models', STORE.models)
    agents=data.get('agents', STORE.agents)
    rules=data.get('rules', STORE.rules)
    if not models: issues.append('no models configured')
    if not agents: issues.append('no agents configured')
    if not rules: issues.append('no rules configured')
    required_agents={'OrchestratorAgent','IntentAgent','PlannerAgent','VerifierAgent','DeployAgent','TelemetryAgent','DiagnosisAgent','HealingAgent'}
    have=set(agents.keys()) if isinstance(agents, dict) else {a.get('name') for a in agents}
    missing=sorted(required_agents-have)
    if missing: issues.append('missing agents: '+','.join(missing))
    return {'valid': not issues, 'issues': issues, 'models': len(models), 'agents': len(agents), 'rules': len(rules)}

@router.get('/api/config/export.yaml', response_class=PlainTextResponse)
def config_export_yaml():
    import yaml
    def to_plain(x):
        if hasattr(x, 'model_dump'): return x.model_dump(mode='json')
        if isinstance(x, dict): return {k: to_plain(v) for k,v in x.items()}
        if isinstance(x, list): return [to_plain(v) for v in x]
        return x
    return yaml.safe_dump(to_plain(config_export()), allow_unicode=True, sort_keys=False)

@router.post('/api/config/import.yaml')
def config_import_yaml(body: str = Body(..., media_type='text/plain')):
    import yaml
    payload=yaml.safe_load(body) or {}
    return config_import(payload)

@router.get('/api/config/credentials')
def credentials():
    return [{**c.model_dump(mode='json'), 'secret_ref':'***' if c.secret_ref else ''} for c in STORE.credentials.values()]

@router.post('/api/config/credentials')
def upsert_credential(c: CredentialConfig):
    STORE.credentials[c.id]=c
    return {**c.model_dump(mode='json'), 'secret_ref':'***' if c.secret_ref else ''}

@router.delete('/api/config/credentials/{credential_id}')
def delete_credential(credential_id: str):
    STORE.credentials.pop(credential_id, None)
    return {'ok': True, 'deleted': credential_id}
