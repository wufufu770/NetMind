from __future__ import annotations
import os, subprocess
from .base import NetworkDriver
from ..schemas import CommandResult

class MininetDriver(NetworkDriver):
    name='mininet'
    real=True
    def execute(self, command: str) -> CommandResult:
        if os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false').lower() != 'true':
            return CommandResult(command=command, success=True, output='real command disabled; mininet dry-run')
        try:
            res=subprocess.run(command, shell=True, check=False, capture_output=True, text=True, timeout=12)
            return CommandResult(command=command, success=res.returncode==0, output=(res.stdout or res.stderr)[:4000])
        except Exception as exc:
            return CommandResult(command=command, success=False, output=str(exc))
