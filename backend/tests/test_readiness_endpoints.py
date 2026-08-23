from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_readiness_endpoint():
    r=client.get('/api/readiness')
    assert r.status_code==200
    data=r.json()
    assert data['ready'] is True
    assert data['rules'] >= 35

def test_notifications_endpoint_after_warning():
    client.post('/api/experiment/fault', json={'kind':'congestion'})
    rows=client.get('/api/notifications').json()
    assert isinstance(rows, list)
    assert any(x['source'] in {'experiment','healing','verify','security'} for x in rows)
