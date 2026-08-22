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

    def execute(self, command: str) -> CommandResult:
        if not _real_commands_enabled():
            return CommandResult(command=command, success=True, output='ssh driver dry-run; set NETMIND_ENABLE_REAL_COMMANDS=true with credentials to reach real devices', requires_approval=True)
        try:
            conn=self._connect()
            output=conn.send_command(command)
            return CommandResult(command=command, success=True, output=output)
        except Exception as exc:
            self._connection=None
            return CommandResult(command=command, success=False, output=f'ssh execution failed: {exc}')

    def collect(self) -> dict:
        try:
            from napalm import get_network_driver
        except ImportError:
            return {'supported': False, 'reason': 'napalm is required for read-only collection: pip install -r requirements-drivers.txt'}
        if not self.host or not self.username:
            return {'supported': False, 'reason': 'credentials missing: set NETMIND_SSH_* environment variables'}
        try:
            napalm_device=os.getenv('NETMIND_NAPALM_DRIVER', self.device_type)
            device=get_network_driver(napalm_device)(hostname=self.host, username=self.username, password=self.password, optional_args={'port': self.port})
            device.open()
            try:
                facts=device.get_facts()
                interfaces=device.get_interfaces()
            finally:
                device.close()
            return {'supported': True, 'host': self.host, 'facts': facts, 'interfaces': interfaces}
        except Exception as exc:
            return {'supported': False, 'reason': f'collection failed: {exc}'}

    def snapshot(self) -> dict:
        return {'driver': self.name, 'real': self.real, 'host': self.host, 'connected': self._connection is not None, 'real_commands_enabled': _real_commands_enabled()}
