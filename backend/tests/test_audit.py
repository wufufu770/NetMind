import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.audit import run_audit, render_markdown, _assert_readonly, ReadonlyViolation

client = TestClient(app)


def test_simulated_run_labeled_and_structured():
    r = run_audit()
    assert r['mode'] == 'simulated'
    assert '模拟数据' in render_markdown(r)
    assert set(r['summary']) == {'ok', 'warn', 'fail'}
    assert len(r['checks']) == 6
    ids = {c['id'] for c in r['checks']}
    assert {'firmware', 'upnp', 'wireless_encryption', 'listening_ports'} <= ids


def test_seeded_findings_surface():
    r = run_audit()
    by = {c['id']: c for c in r['checks']}
    assert by['upnp']['status'] == 'warn'
    assert by['ssh_password_auth']['status'] == 'warn'
    assert by['wireless_encryption']['status'] == 'fail'
    assert by['firewall_rules']['status'] in ('ok', 'warn')


def test_all_commands_are_readonly():
    from app.core.audit import CHECKS, READONLY_GUARD
    for chk in CHECKS:
        for cmd in chk['commands']:
            assert READONLY_GUARD.match(cmd), cmd
            low = ' ' + cmd.lower() + ' '
            for w in (' set ', ' add ', ' del ', ' rm ', ' flush ', ' passwd ', ' commit '):
                assert w not in low, (cmd, w)


def test_readonly_guard_rejects_mutations():
    for bad in ['uci set network.wan.proto=dhcp', 'iptables -F', 'reboot', 'uci commit']:
        with pytest.raises(ReadonlyViolation):
            _assert_readonly([bad])


def test_real_mode_requires_gate(monkeypatch):
    monkeypatch.setenv('NETMIND_AUDIT_MODE', 'real')
    with pytest.raises(PermissionError):
        run_audit()


def test_api_endpoints():
    checks = client.get('/api/audit/checks').json()
    assert len(checks) >= 5 and all(c['commands'] for c in checks)
    r = client.post('/api/audit/run', json={'note': 'ci'})
    assert r.status_code == 200
    body = r.json()
    assert body['mode'] == 'simulated' and 'report_path' in body
    md = client.get(f"/api/audit/{body['audit_id']}/report.md")
    assert md.status_code == 200 and '只读巡检报告' in md.text


def test_cli_registers_audit_command():
    from typer.testing import CliRunner
    from app.cli import app as cli_app
    res = CliRunner().invoke(cli_app, ['--help'])
    assert res.exit_code == 0
    assert 'audit' in res.output and 'audit-summary' in res.output
