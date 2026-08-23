from app.core.security import SECURITY


def test_del_flows_requires_approval_on_any_device():
    for cmd in ['ovs-ofctl del-flows s1', 'ovs-ofctl del-flows s2', 'ovs-ofctl del-flows sw-backup-7']:
        res = SECURITY.check(cmd)
        assert res.success is False, cmd
        assert res.blocked or res.requires_approval, cmd
        target = cmd.split()[2]
        assert target in res.output, (cmd, res.output)


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


def test_rollback_allows_only_netmind_owned_rules():
    owned = 'ovs-ofctl del-flows s1 cookie=0x4e65744d00000001/-1'
    assert SECURITY.check(owned, allow_dangerous=True).success is True

    forged = 'ovs-ofctl del-flows s2 cookie=0xDEADBEEF00000001/-1'
    rb = SECURITY.check(forged, allow_dangerous=True)
    assert rb.success is False and (rb.blocked or rb.requires_approval)

    bare = 'ovs-ofctl del-flows s2'
    rb2 = SECURITY.check(bare, allow_dangerous=True)
    assert rb2.success is False and (rb2.blocked or rb2.requires_approval)


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
