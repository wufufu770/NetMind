"""Linux 系只读采集的回归。

这条路径存在的原因是：napalm 5.2 核心驱不了 Linux/FRR，而实验室拓扑正是这类型。
原实现只挂了 napalm 一条路，于是这类设备在 collect 时必然失败；实测 netmiko 的
device_type='linux' 可用，补上后诚实表的「read-only device collection ✅ Real」
才真正为真。

测试用假连接，不碰真设备——CI 里没有 SSH 端点。
"""
import sys
import types

from app.diagnose.linux_collect import (READONLY_COMMANDS, _looks_like_error,
                                        collect_linux_like, is_linux_like)


class _FakeConn:
    def __init__(self, replies, fail_on=()):
        self.replies = replies
        self.fail_on = set(fail_on)
        self.sent = []
        self.disconnected = False

    def send_command(self, cmd):
        self.sent.append(cmd)
        if cmd in self.fail_on:
            raise RuntimeError('boom')
        return self.replies.get(cmd, '')

    def disconnect(self):
        self.disconnected = True


def _install_fake(monkeypatch, conn):
    mod = types.ModuleType('netmiko')

    def ConnectHandler(**kw):
        conn.kwargs = kw
        return conn
    mod.ConnectHandler = ConnectHandler
    monkeypatch.setitem(sys.modules, 'netmiko', mod)


def test_is_linux_like_covers_container_kinds():
    for k in ('linux', 'alpine', 'frr', 'debian', 'ubuntu', 'busybox'):
        assert is_linux_like(k) is True, k
    for k in ('ceos', 'vr-vmx', 'srl', 'vyos', ''):
        assert is_linux_like(k) is False, k


def test_collects_three_readonly_facts(monkeypatch):
    conn = _FakeConn({'ip addr show': '1: lo: <UP> lo',
                      'ip route show': 'default via 192.168.1.1 dev eth0',
                      'cat /proc/uptime': '123.45 678.90'})
    _install_fake(monkeypatch, conn)
    data, why = collect_linux_like('dev1', '10.0.0.1', 'u', 'p', port=2222)
    assert why == '' and data is not None
    assert data['transport'] == 'netmiko/linux'
    assert data['collected']['routes'].startswith('default via')
    assert 'partial' not in data, '三项都成功时不应标 partial'


WRITE_MARKERS = (' del ', 'add ', 'set ', 'commit', 'write', 'configure')


def test_only_runs_readonly_commands(monkeypatch):
    conn = _FakeConn({c: 'x' for c in READONLY_COMMANDS.values()})
    _install_fake(monkeypatch, conn)
    collect_linux_like('d', 'h', 'u', 'p')
    for cmd in conn.sent:
        low = cmd.lower()
        hit = [w for w in WRITE_MARKERS if w in low]
        assert not hit, f'采集路径出现了疑似写操作 {hit}: {cmd}'


def test_usage_text_is_not_stored_as_data(monkeypatch):
    """BusyBox 的 ip 不认 -br，会把用法说明打回来。收下来就是假数据。"""
    conn = _FakeConn({'ip addr show': 'BusyBox v1.37\n\nUsage: ip [OPTIONS] address|route',
                      'ip route show': 'default via 192.168.1.1 dev eth0',
                      'cat /proc/uptime': '1 2'})
    _install_fake(monkeypatch, conn)
    data, _ = collect_linux_like('d', 'h', 'u', 'p')
    assert data['collected']['interfaces'] is None, '用法文本被当成采集结果存下来了'
    assert any('interfaces' in x for x in data['partial'])


def test_empty_output_is_marked_failed(monkeypatch):
    conn = _FakeConn({'ip addr show': '', 'ip route show': 'x', 'cat /proc/uptime': '1 2'})
    _install_fake(monkeypatch, conn)
    data, _ = collect_linux_like('d', 'h', 'u', 'p')
    assert data['collected']['interfaces'] is None
    assert any('空输出' in x for x in data['partial'])


def test_command_exception_is_marked_failed_not_crashed(monkeypatch):
    conn = _FakeConn({'ip route show': 'default via 1.1.1.1'},
                     fail_on={'ip addr show'})
    _install_fake(monkeypatch, conn)
    data, why = collect_linux_like('d', 'h', 'u', 'p')
    assert why == '' and data is not None, '单条命令失败不该让整次采集崩掉'
    assert data['collected']['interfaces'] is None
    assert data['collected']['routes'].startswith('default')


def test_disconnect_always_called(monkeypatch):
    conn = _FakeConn({c: 'x' for c in READONLY_COMMANDS.values()})
    _install_fake(monkeypatch, conn)
    collect_linux_like('d', 'h', 'u', 'p')
    assert conn.disconnected is True


def test_connection_failure_returns_reason_not_data(monkeypatch):
    def boom(**kw):
        raise ConnectionRefusedError('refused')
    mod = types.ModuleType('netmiko'); mod.ConnectHandler = boom
    monkeypatch.setitem(sys.modules, 'netmiko', mod)
    data, why = collect_linux_like('d', 'h', 'u', 'p')
    assert data is None
    assert 'SSH 失败' in why and 'ConnectionRefusedError' in why


def test_error_marker_detection():
    assert _looks_like_error('Usage: ip [OPTIONS]')
    assert _looks_like_error('sh: ip: not found')
    assert _looks_like_error('ip: invalid option -- b')
    assert not _looks_like_error('default via 192.168.1.1 dev eth0')
    assert not _looks_like_error('1: lo: <UP> qlen 1000')
