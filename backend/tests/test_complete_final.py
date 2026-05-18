from fastapi.testclient import TestClient
from app.main import app
from app.store import STORE
from app.core.security import SECURITY
from app.core.model_adapter import MODEL_ADAPTER

client=TestClient(app)

def test_all_major_entrypoints_exist():
    for path in ['/','/api/system/status','/api/dashboard','/api/topology','/api/agents','/api/config/export','/api/feature-matrix','/api/drivers']:
        r=client.get(path)
        assert r.status_code == 200, path

def test_scenario_closed_loop_and_persistence():
    r=client.post('/api/experiment/scenario/defense')
    assert r.status_code == 200
    data=r.json()
    assert data['intent']['business'] == 'video_meeting'
    assert len(data['steps']) >= 7
    STORE.save()

def test_rollback_and_security_endpoint():
    ex=client.post('/api/intent/submit', json={'text':'访客网络限速5Mbps，并禁止访问实验室服务器'}).json()
    rb=client.get(f"/api/deploy/{ex['execution_id']}/rollback-plan")
    assert rb.status_code == 200
    sec=client.get('/api/security/check', params={'command':'rm -rf /'})
    assert sec.json()['blocked'] is True

def test_model_adapter_mock_and_report_json():
    assert MODEL_ADAPTER.test('mock')['ok']
    ex=client.post('/api/intent/submit', json={'text':'实验室网络隔离，只允许教师终端访问实验服务器'}).json()
    js=client.get(f"/api/report/{ex['execution_id']}.json")
    assert js.status_code == 200
    md=client.get(f"/api/report/{ex['execution_id']}.md")
    assert 'NetMind 执行报告' in md.text

def test_config_crud_and_approval_flow():
    approval={'title':'清空流表确认','description':'危险操作','payload':{'cmd':'ovs-ofctl del-flows s1'}}
    r=client.post('/api/approvals', json=approval)
    assert r.status_code == 200
    aid=r.json()['approval_id']
    done=client.post(f'/api/approvals/{aid}/approved')
    assert done.json()['status'] == 'approved'
