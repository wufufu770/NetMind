from __future__ import annotations
import os
from abc import ABC, abstractmethod
from ..schemas import CommandResult

class NetworkDriver(ABC):
    name='base'
    real=False
    @abstractmethod
    def execute(self, command: str) -> CommandResult: ...
    def snapshot(self) -> dict: return {'driver': self.name, 'real': self.real}
    def mode(self) -> str:
        if not self.real:
            return 'simulated'
        return 'real' if os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false').lower() == 'true' else 'dry-run'
    def collect(self) -> dict:
        return {'supported': False, 'reason': f'{self.name} driver does not implement read-only collection'}
