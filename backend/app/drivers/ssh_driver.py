from __future__ import annotations
from .base import NetworkDriver
from ..schemas import CommandResult

class SSHDriver(NetworkDriver):
    name='ssh'
    real=True
    def execute(self, command: str) -> CommandResult:
        # Production hook: replace with paramiko execution after credentials are configured.
        return CommandResult(command=command, success=True, output='ssh driver dry-run; configure paramiko credentials for real devices')
