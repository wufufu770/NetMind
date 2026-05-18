from fastapi.testclient import TestClient
from app.main import app
from app.core.security import SECURITY
from app.core.rule_engine import RULE_ENGINE

client=TestClient(app)

def test_submit_closed_loop():
    r=client.post('/api/intent/submit', json={'text':'今晚8点保障答辩视频会议，延迟低于50ms，访客限速5Mbps'})
    assert r.status_code==200
    data=r.json()
    assert data['intent']['business']=='video_meeting'
    assert data['policy_set']['policies']
    assert data['verification']

def test_security_blocks_bad_command():
    res=SECURITY.check('rm -rf /')
    assert res.blocked
    assert not res.success

def test_rule_count():
    from app.store import STORE
    assert len(STORE.rules) >= 35

def test_config_export_and_report():
    ex=client.post('/api/intent/submit', json={'text':'访客网络限速5Mbps，并禁止访问实验室服务器'}).json()
    rep=client.post('/api/report/generate', json={'execution_id':ex['execution_id']})
    assert rep.status_code==200
    assert 'NetMind 执行报告' in rep.text
    cfg=client.get('/api/config/export')
    assert cfg.status_code==200 and 'rules' in cfg.json()

def test_fault_heal():
    assert client.post('/api/experiment/fault', json={'kind':'congestion'}).json()['ok']
    snap=client.get('/api/telemetry/latest').json()
    assert snap['alert']
    diag=client.post('/api/telemetry/diagnose').json()
    assert diag['type'] in ['congestion','anomaly_traffic','link_down']
    heal=client.post('/api/telemetry/heal').json()
    assert heal['success']
