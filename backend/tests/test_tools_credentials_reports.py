from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_audit_yaml_and_node_detail():
    client.post('/api/intent/submit', json={'text':'今晚8点保障答辩视频会议，延迟低于50ms，访客限速5Mbps'})
    assert client.get('/api/audit/summary').status_code==200
    y=client.get('/api/config/export.yaml')
    assert y.status_code==200 and 'models:' in y.text
    node=client.get('/api/topology/nodes/s1')
    assert node.status_code==200 and node.json()['node']['id']=='s1'

def test_tools_workflow_credentials_and_log_search():
    tool=client.post('/api/tools/call', json={'tool_name':'security_check','arguments':{'command':'rm -rf /'}})
    assert tool.status_code==200 and tool.json()['result']['blocked'] is True
    wf=client.post('/api/workflows/run', json={'intent_text':'访客网络限速5Mbps','dry_run':True})
    assert wf.status_code==200 and wf.json()['intent']['business']=='guest_limiting'
    cred=client.post('/api/config/credentials', json={'name':'lab-ovs','driver':'ssh','host':'10.0.0.10','username':'netmind','secret_ref':'secret'})
    assert cred.status_code==200 and cred.json()['secret_ref']=='***'
    logs=client.get('/api/logs/search', params={'q':'intent'})
    assert logs.status_code==200

def test_report_options_and_model_binding():
    ex=client.post('/api/intent/submit', json={'text':'实验室网络隔离，只允许教师终端访问实验服务器'}).json()
    md=client.post('/api/report/generate/options', json={'execution_id':ex['execution_id'], 'include_logs':True})
    assert md.status_code==200 and 'NetMind 执行报告' in md.text
    bind=client.post('/api/config/models/mock/bind-agent/PlannerAgent')
    assert bind.status_code==200 and bind.json()['model_id']=='mock'
