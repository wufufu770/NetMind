from __future__ import annotations
from abc import ABC, abstractmethod
from ..schemas import CommandResult

class NetworkDriver(ABC):
    name='base'
    real=False
    @abstractmethod
    def execute(self, command: str) -> CommandResult: ...
    def snapshot(self) -> dict: return {'driver': self.name, 'real': self.real}
    def collect(self) -> dict:
        return {'supported': False, 'reason': f'{self.name} driver does not implement read-only collection'}
