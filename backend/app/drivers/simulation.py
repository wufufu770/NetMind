from __future__ import annotations
from .base import NetworkDriver
from ..schemas import CommandResult

class SimulationDriver(NetworkDriver):
    name='simulation'
    real=False
    def __init__(self): self.commands=[]
    def execute(self, command: str) -> CommandResult:
        self.commands.append(command)
        return CommandResult(command=command, success=True, output='simulated execution ok')
    def snapshot(self) -> dict:
        return {'driver': self.name, 'real': self.real, 'executed_commands': len(self.commands)}
