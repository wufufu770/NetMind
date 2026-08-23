from app.core.security import SECURITY
from app.store import STORE


def test_del_flows_requires_approval_on_any_device():
    for cmd in ['ovs-ofctl del-flows s1', 'ovs-ofctl del-flows s2', 'ovs-ofctl del-flows sw-backup-7']:
        res = SECURITY.check(cmd)
        assert res.success is False, cmd
        assert res.blocked or res.requires_approval, cmd
        target = cmd.split()[2]
        assert target in res.output, (cmd, res.output)


def test_extended_dangerous_ops_gated():
    for cmd in [
        'ovs-ofctl mod-flows s1',
        'ip link set s1-eth0 down',
        'ip route del 10.0.0.0/24',
        'ip addr del 192.168.1.10/24 dev s1-eth0',
        'iptables -F OUTPUT',
    ]:
        res = SECURITY.check(cmd)
        assert res.success is False, (cmd, res.output)
        assert res.blocked or res.requires_approval, cmd


def test_iptables_flush_requires_approval_on_any_chain():
    for cmd in ['iptables -F FORWARD', 'iptables -F INPUT', 'iptables -F DOCKER-USER']:
        res = SECURITY.check(cmd)
        assert res.success is False, cmd
        assert res.blocked or res.requires_approval, cmd


def test_read_only_ops_stay_allowed_without_approval():
    for cmd in ['ovs-ofctl dump-flows s2', 'ovs-ofctl dump-ports s9', 'iptables -L FORWARD']:
        res = SECURITY.check(cmd)
        assert res.success is True, (cmd, res.output)
        assert not res.blocked and not res.requires_approval


def test_rollback_requires_registered_cookie():
    # 使用本测试独有的 cookie，避免同进程其他用例（闭环部署）登记的 cookie 串扰
    unregistered = 'ovs-ofctl del-flows s1 cookie=0x4e65744d5afe0002/-1'
    rb = SECURITY.check(unregistered, allow_dangerous=True)
    assert rb.success is False and (rb.blocked or rb.requires_approval)

    # 系统登记后（部署入口的语义）→ 放行
    STORE.register_flow_cookies([unregistered], 'exec-test-reg')
    assert SECURITY.check(unregistered, allow_dangerous=True).success is True

    # 伪造 cookie（格式对但从未签发）→ 仍拦截
    forged = 'ovs-ofctl del-flows s2 cookie=0x4e65744dbadc0003/-1'
    rb2 = SECURITY.check(forged, allow_dangerous=True)
    assert rb2.success is False and (rb2.blocked or rb2.requires_approval)

    # 裸危险命令（无 cookie）→ 拦截
    bare = 'ovs-ofctl del-flows s2'
    rb3 = SECURITY.check(bare, allow_dangerous=True)
    assert rb3.success is False and (rb3.blocked or rb3.requires_approval)


def test_blacklist_still_wins_on_rollback_path():
    res = SECURITY.check('rm -rf /', allow_dangerous=True)
    assert res.success is False and res.blocked is True


def test_invalid_cookie_still_blocked_on_forward_path():
    res = SECURITY.check('ovs-ofctl add-flow s1 cookie=0xdeadbeefdeadbeef')
    assert res.success is False and res.blocked is True


def test_tc_interface_policy_relaxes_for_real_devices(monkeypatch):
    monkeypatch.setenv('NETMIND_DRIVER', 'ssh')
    monkeypatch.setenv('NETMIND_ENABLE_REAL_COMMANDS', 'true')
    ok = SECURITY.check('tc qdisc del dev eth0 root')
    assert ok.success is True, ok.output

    bad = SECURITY.check('tc qdisc del dev "bad name" root')
    assert bad.success is False and bad.blocked is True

    monkeypatch.setenv('NETMIND_DRIVER', 'simulation')
    strict = SECURITY.check('tc qdisc del dev eth0 root')
    assert strict.success is False and strict.blocked is True


def test_snapshot_reports_semantic_approval_required():
    snap = SECURITY.snapshot()
    assert any('del-flows' in p for p in snap['approval_required'])
    assert any('-F' in p for p in snap['approval_required'])


def test_rollback_endpoint_registration_flow():
    """闭环部署登记 cookie 后，合法回滚放行；伪造 cookie 与未部署执行被拒。"""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    ex = client.post('/api/intent/submit', json={'text': '访客网络限速5Mbps'}).json()
    eid = ex['execution_id']
    assert ex.get('deploy') is not None, 'closed loop 应已部署'

    # 合法回滚：cookie 已在部署时登记
    r = client.post(f'/api/deploy/{eid}/rollback')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['rolled_back'] is True and body['rollback_complete'] is True

    # 未部署过的执行 → 409
    from app.store import STORE
    from app.schemas import Execution
    fresh = Execution(intent_text='never-deployed')
    STORE.put_execution(fresh)
    r2 = client.post(f"/api/deploy/{fresh.execution_id}/rollback")
    assert r2.status_code == 409

    # 伪造 cookie 的策略集无法借道：直接构造未登记危险命令探测门禁
    from app.core.security import SECURITY
    forged = SECURITY.check('ovs-ofctl del-flows s7 cookie=0x4e65744d99999999/-1', allow_dangerous=True)
    assert forged.success is False
