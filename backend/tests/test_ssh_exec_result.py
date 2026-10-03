"""SSH 下发的成败判定。

原来 `SSHDriver.execute()` 无条件返回 `success=True`——只判 SSH 有没有返回，
不判命令是否真的执行。实测：

    tc qdisc show dev eth0            success=True  output='-bash: tc: command not found'
    definitely-not-a-command --x      success=True  output='...: command not found'

也就是说「已真下发」这句话在命令根本没跑的情况下也会成立。部署路径信任
`success` 去做回滚判断，于是回滚决定建立在一个假阳性上。

现在改为取远端退出码：包一层 `cmd; printf ' __netmind_rc=%s\\n' "$?"`，
按标记解析。拿不到标记时不猜成功。
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.drivers.ssh_driver import SSHDriver


class _Conn:
    """模拟远端：按命令真执行并返回真实退出码。"""

    RC = SSHDriver.RC_MARKER

    def __init__(self):
        self.sent = []

    def send_command(self, cmd, **kw):
        self.sent.append(cmd)
        if cmd.startswith('id '):
            return f'\nnetmind\n {self.RC}0\n'
        if 'qdisc show' in cmd:
            return f'\n- bash: tc: command not found\n {self.RC}127\n'
        if 'exit 7' in cmd:
            return f'\n {self.RC}7\n'
        return f'\nok\n {self.RC}0\n'


@pytest.fixture
def drv(monkeypatch):
    monkeypatch.setenv('NETMIND_ENABLE_REAL_COMMANDS', 'true')
    monkeypatch.setenv('NETMIND_SSH_HOST', '10.0.0.1')
    monkeypatch.setenv('NETMIND_SSH_USERNAME', 'u')
    monkeypatch.setenv('NETMIND_SSH_PASSWORD', 'p')
    monkeypatch.setenv('NETMIND_SSH_DEVICE_TYPE', 'linux')
    m = types.ModuleType('netmiko')
    holder = {}

    def factory(**kw):
        conn = _Conn()
        holder['conn'] = conn
        return conn
    m.ConnectHandler = factory
    monkeypatch.setitem(sys.modules, 'netmiko', m)
    d = SSHDriver()
    d._connection = holder.get('conn') or _Conn()
    return d


def test_successful_command_reports_success(drv):
    r = drv.execute('id -un')
    assert r.success is True
    assert 'netmind' in r.output


def test_command_not_found_reports_failure(drv):
    """这条是本文件的全部意义：命令没跑成，不能报成功。"""
    r = drv.execute('tc qdisc show dev eth0')
    assert r.success is False
    assert 'command not found' in r.output


def test_nonzero_exit_reports_failure(drv):
    assert drv.execute('exit 7').success is False


def test_marker_is_stripped_from_output(drv):
    r = drv.execute('id -un')
    assert SSHDriver.RC_MARKER not in r.output, '内部标记不该出现在给用户看的输出里'


def test_command_is_wrapped_with_exit_code_capture(drv):
    drv.execute('id -un')
    sent = drv._connection.sent[-1]
    assert SSHDriver.RC_MARKER in sent, '没包退出码就没法判成败'


def test_missing_marker_is_not_treated_as_success(monkeypatch):
    """远端没回标记（可能根本没执行）时，不猜成功。"""
    monkeypatch.setenv('NETMIND_ENABLE_REAL_COMMANDS', 'true')
    monkeypatch.setenv('NETMIND_SSH_HOST', '10.0.0.1')
    monkeypatch.setenv('NETMIND_SSH_USERNAME', 'u')
    monkeypatch.setenv('NETMIND_SSH_PASSWORD', 'p')
    monkeypatch.setenv('NETMIND_SSH_DEVICE_TYPE', 'linux')
    m = types.ModuleType('netmiko')
    m.ConnectHandler = lambda **kw: type('C', (), {'send_command': staticmethod(lambda c, **kw: '\nsome output without marker\n')})()
    monkeypatch.setitem(sys.modules, 'netmiko', m)
    d = SSHDriver()
    d._connection = m.ConnectHandler()
    r = d.execute('anything')
    assert r.success is False, '拿不到退出码却报成功'


def test_dry_run_path_untouched(monkeypatch):
    """干跑路径的语义不变：明确标注 requires_approval。"""
    monkeypatch.setenv('NETMIND_ENABLE_REAL_COMMANDS', 'false')
    r = SSHDriver().execute('rm -rf /')
    assert 'dry-run' in r.output
    assert r.requires_approval is True
