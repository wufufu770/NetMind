from __future__ import annotations
import os
from .base import NetworkDriver
from ..schemas import CommandResult


def _real_commands_enabled() -> bool:
    return os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false').lower() == 'true'


class SSHDriver(NetworkDriver):
    name='ssh'
    real=True

    def __init__(self):
        self.host=os.getenv('NETMIND_SSH_HOST','')
        self.username=os.getenv('NETMIND_SSH_USERNAME','')
        self.password=os.getenv('NETMIND_SSH_PASSWORD','')
        self.device_type=os.getenv('NETMIND_SSH_DEVICE_TYPE','linux')
        self.port=int(os.getenv('NETMIND_SSH_PORT','22'))
        self._connection=None

    def _connect(self):
        if self._connection is not None:
            return self._connection
        try:
            from netmiko import ConnectHandler
        except ImportError as exc:
            raise RuntimeError('netmiko is required for real SSH execution: pip install -r requirements-drivers.txt') from exc
        if not self.host or not self.username:
            raise RuntimeError('SSH credentials missing: set NETMIND_SSH_HOST / NETMIND_SSH_USERNAME / NETMIND_SSH_PASSWORD')
        self._connection=ConnectHandler(
            device_type=self.device_type,
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
        )
        return self._connection

    # 远端执行结果的判定标记
    RC_MARKER = '__netmind_rc='
    READ_TIMEOUT = 30

    def _wrap(self, command: str) -> str:
        """必要时加 sudo。

        真实网络设备上，监控用的低权账号几乎不能直接改配置——通常靠一个
        受限的提权（sudoers 白名单）来做处置。实验台上 openssh-server 默认
        禁掉 root 密码登录，低权账号走 sudo。

        用 `sudo -n`（非交互）：没有 NOPASSWD 就立刻失败，而不是挂在那儿等
        密码输入。**部署前提：监控账号的 sudoers 条目是 NOPASSWD**——让工具
        去提示输入密码既不可用也不安全。见 docs/DEPLOY.md。
        """
        if os.getenv('NETMIND_SUDO', 'false').lower() in ('1', 'true', 'yes'):
            return 'sudo -n ' + command
        return command

    def execute(self, command: str) -> CommandResult:
        if not _real_commands_enabled():
            return CommandResult(command=command, success=True, output='ssh driver dry-run; set NETMIND_ENABLE_REAL_COMMANDS=true with credentials to reach real devices', requires_approval=True)
        try:
            conn = self._connect()
            # 包一层取远端退出码。原来直接 send_command 再无条件 success=True，
            # 结果「tc: command not found」也算成功——实测过，命令根本没跑却报成功。
            # 这会让「已真下发」这句话彻底失去意义，所以必须用退出码判定。
            wrapped = f'{self._wrap(command)}; printf " {self.RC_MARKER}%s\\n" "$?"'
            # 不传 expect_string：实测在 device_type='linux' 下 netmiko 的
            # expect_string 分支返回空串（读不到任何东西），而普通 send_command
            # 配足 read_timeout 能完整拿到输出含退出码标记。两者都试过。
            output = conn.send_command(wrapped, read_timeout=self.READ_TIMEOUT)
        except Exception as exc:
            self._connection = None
            return CommandResult(command=command, success=False, output=f'ssh execution failed: {exc}')

        text = output if isinstance(output, str) else str(output)
        rc = None
        for line in reversed(text.splitlines()):
            if self.RC_MARKER in line:
                try:
                    rc = int(line.split(self.RC_MARKER)[-1].strip())
                except ValueError:
                    rc = None
                break

        body = '\n'.join(l for l in text.splitlines() if self.RC_MARKER not in l)
        if rc is None:
            # 拿不到退出码时不猜成功——远端没回标记，可能根本没执行
            return CommandResult(command=command, success=False,
                                  output=body.strip() or text.strip(),
                                  )
        ok = rc == 0
        return CommandResult(command=command, success=ok,
                             output=body.strip(),
                             requires_approval=not ok)

    def collect(self) -> dict:
        try:
            from napalm import get_network_driver
        except ImportError:
            return {'supported': False, 'reason': 'napalm is required for read-only collection: pip install -r requirements-drivers.txt'}
        if not self.host or not self.username:
            return {'supported': False, 'reason': 'credentials missing: set NETMIND_SSH_* environment variables'}
        try:
            # 不再把 self.device_type 直接当 napalm 驱动名——device_type 是 netmiko
            # 的取值（cisco_ios / linux / junos …），napalm 的驱动名是另一套
            # （eos / ios / junos / nxos …），linux 在 napalm 里根本不存在。
            # 这与 diagnose/drivers.py 修的是同一个 bug 的两个副本：那次修了
            # 诊断路径，这条下发路径漏了。统一走 pick_driver。
            from ..diagnose.drivers import driver_available, pick_driver
            override=os.getenv('NETMIND_NAPALM_DRIVER', '').strip()
            if override:
                napalm_device=override
                kind, reason = napalm_device, ''
            else:
                napalm_device, reason = pick_driver(self.device_type)
            if not napalm_device:
                return {'supported': False,
                        'reason': f'device_type={self.device_type} 没有对应的 napalm 驱动——{reason}'}
            ok, why = driver_available(napalm_device)
            if not ok:
                return {'supported': False, 'reason': f'napalm 驱动 {napalm_device} 不可用：{why}'}
            device=get_network_driver(napalm_device)(hostname=self.host, username=self.username, password=self.password, optional_args={'port': self.port})
            device.open()
            try:
                facts=device.get_facts()
                interfaces=device.get_interfaces()
            finally:
                device.close()
            return {'supported': True, 'host': self.host, 'driver': napalm_device, 'facts': facts, 'interfaces': interfaces}
        except Exception as exc:
            return {'supported': False, 'reason': f'collection failed: {type(exc).__name__}: {exc}'}

    def snapshot(self) -> dict:
        return {'driver': self.name, 'real': self.real, 'host': self.host, 'connected': self._connection is not None, 'real_commands_enabled': _real_commands_enabled()}
