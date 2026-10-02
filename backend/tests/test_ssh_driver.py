"""SSHDriver 的采集与下发路径回归。

两处修复的锁：
  1. collect() 曾把 netmiko 的 device_type（linux / cisco_ios …）直接当 napalm
     驱动名（eos / ios / junos …）用。linux 在 napalm 里不存在，于是对着
     Linux/FRR 设备采集必然失败，且错误信息是一句含糊的 collection failed。
     这与 diagnose/drivers.py 是同一个 bug 的两个副本——那次修了诊断路径，
     下发路径漏了。
  2. 未知 device_type 曾被静默当成某个 napalm 驱动去连。

下发路径要真连设备，这里用假 netmiko，不碰真设备。
"""
import sys
import types

from app.drivers.ssh_driver import SSHDriver


def _mk_env(monkeypatch, **kw):
    base = {
        'NETMIND_ENABLE_REAL_COMMANDS': 'true',
        'NETMIND_SSH_HOST': '10.0.0.1',
        'NETMIND_SSH_PORT': '2222',
        'NETMIND_SSH_USERNAME': 'u',
        'NETMIND_SSH_PASSWORD': 'p',
        'NETMIND_SSH_DEVICE_TYPE': 'linux',
    }
    base.update(kw)
    for k, v in base.items():
        monkeypatch.setenv(k, v)


def _fake_napalm(monkeypatch, available=('eos', 'ios', 'junos', 'iosxr', 'nxos', 'nxos_ssh')):
    mod = types.ModuleType('napalm')
    real = set(available)

    def get_network_driver(name):
        # 真实 napalm 返回的是**类**，调用方写成 get_network_driver(x)(**kw) 去实例化
        if name not in real:
            raise ImportError(f'Cannot import "{name}". Is the library installed?')

        class _Driver:
            def __init__(self, **kw):
                self.kw = kw
                self.opened = False
            def open(self): self.opened = True
            def close(self): pass
            def get_facts(self): return {'hostname': 'fake'}
            def get_interfaces(self): return {'eth0': {'is_up': True, 'description': ''}}
        return _Driver
    mod.get_network_driver = get_network_driver
    monkeypatch.setitem(sys.modules, 'napalm', mod)


def test_collect_reports_no_driver_for_linux(monkeypatch):
    """Linux/FRR 设备没有 napalm 驱动——要说清，不要含糊的 collection failed。"""
    _mk_env(monkeypatch)
    _fake_napalm(monkeypatch)
    r = SSHDriver().collect()
    assert r['supported'] is False
    assert 'napalm' in r['reason']
    assert 'linux' in r['reason']


def test_collect_maps_device_type_through_pick_driver(monkeypatch):
    """cisco_ios 是 netmiko 的 device_type，对应 napalm 的 ios 驱动。"""
    _mk_env(monkeypatch, NETMIND_SSH_DEVICE_TYPE='cisco_ios')
    _fake_napalm(monkeypatch)
    r = SSHDriver().collect()
    assert r['supported'] is True, r.get('reason')
    assert r['driver'] == 'ios', f"应映射到 ios，实际 {r.get('driver')}"


def test_collect_unknown_device_type_is_not_guessed(monkeypatch):
    """未知 device_type 不得被静默当成某个驱动去连。"""
    _mk_env(monkeypatch, NETMIND_SSH_DEVICE_TYPE='totally-unknown-os')
    _fake_napalm(monkeypatch)
    r = SSHDriver().collect()
    assert r['supported'] is False
    assert '驱动' in r['reason']


def test_collect_respects_explicit_override(monkeypatch):
    """运维显式指定的 NETMIND_NAPALM_DRIVER 优先于自动映射。"""
    _mk_env(monkeypatch, NETMIND_SSH_DEVICE_TYPE='linux', NETMIND_NAPALM_DRIVER='eos')
    _fake_napalm(monkeypatch)
    r = SSHDriver().collect()
    assert r['supported'] is True, r.get('reason')
    assert r['driver'] == 'eos'


def test_collect_reports_plugin_missing_clearly(monkeypatch):
    _mk_env(monkeypatch, NETMIND_SSH_DEVICE_TYPE='srl')
    _fake_napalm(monkeypatch)          # srl 不在可用集合里
    r = SSHDriver().collect()
    assert r['supported'] is False
    assert 'srl' in r['reason'] or 'napalm' in r['reason']


def test_execute_is_dry_run_unless_explicitly_enabled(monkeypatch):
    """默认干跑——真实执行必须显式开开关。"""
    _mk_env(monkeypatch, NETMIND_ENABLE_REAL_COMMANDS='false')
    r = SSHDriver().execute('rm -rf /')
    assert r.success is True
    assert 'dry-run' in r.output
    assert r.requires_approval is True


def test_execute_really_runs_when_enabled(monkeypatch):
    sent = []

    class Conn:
        def send_command(self, cmd):
            sent.append(cmd)
            return 'real-output'

        def disconnect(self):
            pass
    netmiko = types.ModuleType('netmiko')
    netmiko.ConnectHandler = lambda **kw: Conn()
    monkeypatch.setitem(sys.modules, 'netmiko', netmiko)
    _mk_env(monkeypatch)
    r = SSHDriver().execute('show version')
    assert r.success is True and r.output == 'real-output'
    assert sent == ['show version'], '命令必须真发到设备上'


def test_execute_failure_is_reported_not_swallowed(monkeypatch):
    netmiko = types.ModuleType('netmiko')

    def boom(**kw):
        raise ConnectionError('refused')
    netmiko.ConnectHandler = boom
    monkeypatch.setitem(sys.modules, 'netmiko', netmiko)
    _mk_env(monkeypatch)
    r = SSHDriver().execute('show version')
    assert r.success is False
    assert 'refused' in r.output
