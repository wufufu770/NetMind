from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_snapshot_restore_validate_yaml_import():
    snap=client.get('/api/store/snapshot')
    assert snap.status_code==200 and 'templates' in snap.json()
    restored=client.post('/api/store/restore', json={'templates':{'round4':'测试模板'}})
    assert restored.status_code==200
    valid=client.post('/api/config/validate')
    assert valid.status_code==200 and valid.json()['valid'] is True
    y=client.post('/api/config/import.yaml', content='theme:\n  primary: "#2970FF"\n  background: "#0D1117"\n  card: "#161B22"\n  radius: 8\n  font: Inter\n', headers={'Content-Type':'text/plain'})
    assert y.status_code==200

def test_report_bundle_and_pdf():
    ex=client.post('/api/intent/submit', json={'text':'今晚8点保障答辩视频会议，延迟低于50ms'}).json()
    b=client.get(f"/api/report/{ex['execution_id']}/bundle")
    assert b.status_code==200 and 'markdown' in b.json()
    pdf=client.get(f"/api/report/{ex['execution_id']}.pdf")
    assert pdf.status_code==200
    assert pdf.headers['content-type'].startswith('application/pdf')
