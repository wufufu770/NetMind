from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_openapi_contains_core_routes():
    data=client.get('/openapi.json').json()
    paths=data['paths']
    for path in ['/api/intent/submit','/api/feature-matrix','/api/audit/summary','/api/store/snapshot','/api/report/{execution_id}.pdf']:
        assert path in paths

def test_full_competition_closed_loop_smoke():
    ex=client.post('/api/intent/submit', json={'text':'今晚8点保障答辩视频会议，教师终端到会议服务器延迟低于50ms，访客网络限速5Mbps'}).json()
    eid=ex['execution_id']
    assert ex['intent']['business']=='video_meeting'
    assert ex['policy_set']['policies']
    assert ex['verification']['passed'] is True
    assert client.get(f'/api/executions/{eid}/replay').status_code==200
    assert client.get(f'/api/report/{eid}.md').status_code==200
    assert client.get('/api/system/completeness').json()['entrypoints']==66
