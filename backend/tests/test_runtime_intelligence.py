from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_model_health_offline_ambiguity_and_template_suggest():
    h=client.post('/api/system/model-health-check')
    assert h.status_code==200 and 'results' in h.json()
    amb=client.post('/api/intent/resolve-ambiguity', json={'text':'请保障今晚的网络'}).json()
    assert amb['ambiguous'] is True
    assert len(amb['candidates']) >= 2
    sug=client.post('/api/template-suggestions', json={'text':'今晚8点保障答辩视频会议，延迟低于50ms'}).json()
    assert sug['business']=='video_meeting'
    assert 'similar_templates' in sug

def test_agent_schedule_and_recovery_review():
    s=client.put('/api/config/agents/TelemetryAgent/schedule', json={'enabled':False,'active_schedule':'0 2 * * *'}).json()
    assert s['enabled'] is False
    got=client.get('/api/config/agents/TelemetryAgent/schedule').json()
    assert got['active_schedule']=='0 2 * * *'
    review=client.post('/api/system/ai-recovery-review').json()
    assert 'reviewed' in review
