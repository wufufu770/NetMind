from __future__ import annotations
import os
from .base import NetworkDriver
from ..schemas import CommandResult


class NETCONFDriver(NetworkDriver):
    name='netconf'
    real=True

    def __init__(self):
        self.host=os.getenv('NETMIND_NETCONF_HOST','')
        self.port=int(os.getenv('NETMIND_NETCONF_PORT','830'))
        self.username=os.getenv('NETMIND_NETCONF_USERNAME','')
        self.password=os.getenv('NETMIND_NETCONF_PASSWORD','')
        self._manager=None

    def _connect(self):
        if self._manager is not None:
            return self._manager
        try:
            from ncclient import manager
        except ImportError as exc:
            raise RuntimeError('ncclient is required for real NETCONF: pip install -r requirements-drivers.txt') from exc
        if not self.host or not self.username:
            raise RuntimeError('NETCONF endpoint missing: set NETMIND_NETCONF_HOST / NETMIND_NETCONF_USERNAME / NETMIND_NETCONF_PASSWORD')
        self._manager=manager.connect(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            hostkey_verify=False,
        )
        return self._manager

    def execute(self, command: str) -> CommandResult:
        if os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false').lower() != 'true':
            return CommandResult(command=command, success=True, output='netconf driver dry-run; set NETMIND_ENABLE_REAL_COMMANDS=true with credentials to reach real devices', requires_approval=True)
        try:
            m=self._connect()
            response=m.dispatch(command.strip())
            return CommandResult(command=command, success=True, output=str(response.xml)[:8000])
        except Exception as exc:
            self._manager=None
            return CommandResult(command=command, success=False, output=f'netconf execution failed: {exc}')

    def collect(self) -> dict:
        try:
            m=self._connect()
            running=m.get_config(source='running')
            return {'supported': True, 'host': self.host, 'capabilities': sorted(m.server_capabilities)[:40], 'running_config': str(running.xml)[:8000]}
        except Exception as exc:
            return {'supported': False, 'reason': f'collection failed: {exc}'}

    def snapshot(self) -> dict:
        return {'driver': self.name, 'real': self.real, 'host': self.host, 'port': self.port, 'connected': self._manager is not None, 'real_commands_enabled': os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false')}
