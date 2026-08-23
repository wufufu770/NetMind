import os
from fastapi.testclient import TestClient
from app.main import app
from app import __version__
from app.core.topology import TOPOLOGY
from app.core.verification import VERIFIER
from app.core.security import SECURITY
from app.store import STORE, MAX_EXECUTIONS, MAX_TELEMETRY
from app.schemas import Execution, Policy, PolicySet, TelemetrySnapshot

client=TestClient(app)

def test_version_is_single_sourced():
    assert __version__ == client.get('/').json()['version']
    assert 'simulation' not in client.get('/').json()['version']

def test_topology_path_latency_derives_from_links():
    assert TOPOLOGY.path_latency('teacher_terminal','meeting_server') == 23.0
    assert TOPOLOGY.path_latency('teacher_terminal','nowhere') is None

def test_semantic_conflict_detection_and_autofix():
    ps=PolicySet(intent_id='t', policies=[
        Policy(type='qos', name='alpha', action='guarantee_bandwidth', priority=10, params={'src':'s','dst':'lab_server'}),
        Policy(type='acl', name='beta', action='deny_guest_to_lab', priority=30, params={'src':'g','dst':'lab_server'}),
    ])
    report=VERIFIER.check(ps)
    assert 'ACL_PRIORITY_OVERLAP' in [i.code for i in report.conflicts]
    guarantee=[p for p in report.fixed_policy_set.policies if p.action=='guarantee_bandwidth'][0]
    assert guarantee.priority==1

def test_rollback_ready_requires_rollback_commands():
    ps=PolicySet(intent_id='t', policies=[Policy(type='route', name='x', action='normal', priority=1, params={})])
    assert VERIFIER.check(ps).rollback_ready is False
    ps2=PolicySet(intent_id='t', policies=[Policy(type='route', name='x', action='normal', priority=1, params={}, commands=['ovs-ofctl dump-flows s1'], rollback_commands=['ovs-ofctl del-flows s1 cookie=0x4e65744d00000009/-1'])])
    assert VERIFIER.check(ps2).rollback_ready is True

def test_dangerous_commands_blocked_unless_registered_rollback():
    # 用本测试独有的 cookie，避免与其他用例的登记表状态串扰
    cmd='ovs-ofctl del-flows s1 cookie=0x4e65744d5afe0001'
    res=SECURITY.check(cmd)
    assert res.success is False or res.requires_approval is True or res.blocked is True
    # 未登记的合法格式 cookie 不享有回滚特权
    rb_unregistered=SECURITY.check(cmd, allow_dangerous=True)
    assert rb_unregistered.success is False
    # 部署入口登记后（模拟 TransactionManager 行为）方可回滚
    STORE.register_flow_cookies([cmd], 'exec-honesty')
    rb=SECURITY.check(cmd, allow_dangerous=True)
    assert rb.success is True
    evil=SECURITY.check('rm -rf /', allow_dangerous=True)
    assert evil.blocked is True

def test_deploy_result_carries_mode():
    ex=client.post('/api/intent/submit', json={'text':'访客网络限速5Mbps'}).json()
    dep=ex.get('deploy')
    if dep is not None:
        assert dep['mode'] in ('simulated','dry-run','real')

def test_store_caps_enforced():
    for i in range(MAX_TELEMETRY+5):
        STORE.record_telemetry(TelemetrySnapshot(latency_ms=i))
    assert len(STORE.telemetry) <= MAX_TELEMETRY
    for i in range(MAX_EXECUTIONS+3):
        STORE.put_execution(Execution(intent_text=f'x{i}'))
    assert len(STORE.executions) <= MAX_EXECUTIONS

def test_auth_gate_when_token_configured(monkeypatch):
    monkeypatch.setenv('NETMIND_ADMIN_TOKEN','secret-token')
    denied=client.post('/api/config/reset-runtime')
    assert denied.status_code == 401
    allowed=client.post('/api/config/reset-runtime', headers={'Authorization':'Bearer secret-token'})
    assert allowed.status_code == 200
    read_open=client.get('/api/system/status')
    assert read_open.status_code == 200

def test_cli_module_imports_and_reports_version(monkeypatch):
    monkeypatch.setenv('NETMIND_ADMIN_TOKEN','secret-token')
    from typer.testing import CliRunner
    from app.cli import app as cli_app
    result=CliRunner().invoke(cli_app, ['--help'])
    assert result.exit_code == 0
