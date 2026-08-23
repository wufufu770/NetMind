from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_conflict_matrix_and_auto_fix():
    ex=client.post('/api/intent/submit', json={'text':'今晚8点保障答辩视频会议，访客网络限速5Mbps', 'dry_run':True}).json()
    matrix=client.get('/api/policy/conflict-matrix').json()
    assert 'acl' in matrix and 'qos' in matrix
    fixed=client.post(f"/api/policy/{ex['execution_id']}/auto-fix")
    assert fixed.status_code==200
    assert 'passed' in fixed.json()

def test_approval_create_approve_execute_path():
    ex=client.post('/api/intent/submit', json={'text':'实验室网络隔离，只允许教师终端访问实验服务器','dry_run':True}).json()
    appr=client.post(f"/api/approval-requests/from-execution/{ex['execution_id']}").json()
    assert appr['status']=='pending'
    approved=client.post(f"/api/approvals/{appr['approval_id']}/approved")
    assert approved.status_code==200
    executed=client.post(f"/api/approval-requests/{appr['approval_id']}/execute")
    assert executed.status_code==200
    assert 'executed' in executed.json()
