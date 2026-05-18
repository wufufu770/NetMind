from fastapi.testclient import TestClient
from app.main import app
from app.store import STORE

client = TestClient(app)


def test_template_suggest_create_list_delete_roundtrip():
    sug = client.post('/api/template-manager/suggest', json={'text':'今晚保障答辩视频会议，延迟低于50ms'}).json()
    assert sug['business'] == 'video_meeting'
    assert 'matches' in sug
    created = client.post('/api/template-manager/create', json={'template_id':'custom_defense','text':'自定义答辩保障模板，访客限速5Mbps'}).json()
    assert created['storage'] == 'persistent_store.templates'
    rows = client.get('/api/template-manager/list').json()
    assert any(r['template_id'] == 'custom_defense' for r in rows)
    deleted = client.delete('/api/template-manager/custom_defense').json()
    assert deleted['deleted'] == 'custom_defense'


def test_agent_add_update_delete_and_prompt_recommendations():
    agent = {'name':'CustomAuditAgent','level':'secondary','model_id':'mock','allowed_tools':['free_state_explainer'],'prompt':'只读审计 Agent，输出审计摘要。'}
    up = client.post('/api/config/agents', json=agent).json()
    assert up['name'] == 'CustomAuditAgent'
    prompts = client.get('/api/config/agents/prompts/recommended').json()
    assert 'PlannerAgent' in prompts
    gone = client.delete('/api/config/agents/CustomAuditAgent').json()
    assert gone['existed'] is True


def test_workflow_save_catalog_run_and_delete():
    wf = {'id':'custom_test_flow','name':'自定义测试工作流','graph':{'nodes':['OrchestratorAgent','IntentAgent','PlannerAgent'],'edges':[['OrchestratorAgent','IntentAgent'],['IntentAgent','PlannerAgent']]},'enabled':True}
    saved = client.post('/api/config/workflows', json=wf).json()
    assert saved['id'] == 'custom_test_flow'
    catalog = client.get('/api/workflows/catalog').json()
    assert any(x['id'] == 'custom_test_flow' for x in catalog)
    run = client.post('/api/workflows/run', json={'workflow_id':'custom_test_flow','intent_text':'访客网络限速5Mbps','dry_run':True}).json()
    assert run['steps'][0]['output']['workflow_id'] == 'custom_test_flow'
    deleted = client.delete('/api/config/workflows/custom_test_flow').json()
    assert deleted['existed'] is True


def test_free_tools_are_callable_and_planner_step_records_tool_context():
    tools = client.get('/api/tools').json()
    names = {t['name'] for t in tools}
    assert {'free_latency_probe','free_sla_estimator','free_path_finder','free_cron_explain'} <= names
    cron = client.post('/api/cron/explain', json={'cron':'0 2 * * *'}).json()
    assert cron['result']['description'] == '每天 02:00 执行'
    ex = client.post('/api/intent/submit', json={'text':'今晚保障答辩视频会议，延迟低于50ms','dry_run':True}).json()
    planner = next(s for s in ex['steps'] if s['agent'] == 'PlannerAgent')
    tool_names = {t['name'] for t in planner['tools']}
    assert 'free_path_finder' in tool_names
    assert 'free_sla_estimator' in tool_names


def test_cross_domain_explanation_and_cron_presets():
    exp = client.get('/api/workflows/explain/cross-domain').json()
    assert 'proposal' in exp['meaning'] or exp['rounds']
    presets = client.get('/api/cron/presets').json()
    assert any(p['id'] == 'custom' for p in presets)
