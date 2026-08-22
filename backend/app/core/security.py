from __future__ import annotations
import re
from ..schemas import CommandResult

class SecurityChecker:
    def __init__(self):
        self.blacklist=['rm','dd','mkfs','reboot','shutdown','poweroff','kill','pkill','chmod 777','wget','curl','>','>>','|',';','&&','`','$(']
        self.allow_patterns=[
            r'^ovs-ofctl (add-flow|del-flows|mod-flows|dump-flows|dump-ports) [a-zA-Z0-9_.:=,/-]+.*$',
            r'^ovs-vsctl (show|list-ports|list-ifaces).*$',
            r'^tc (qdisc|class|filter) (add|del|show).*$',
            r'^iptables (-A|-D|-I|-L|-F|-N) (INPUT|OUTPUT|FORWARD).*$',
            r'^ip (link set|addr add|addr del|route add|route del).*$',
            r'^ping -c ([1-9]|10) .+$',
            r'^iperf3 .+$'
        ]
        self.dangerous_legal=['ovs-ofctl del-flows s1','iptables -F FORWARD','iptables -F INPUT','iptables -F OUTPUT']
        self.unattended_policy='deny'

    def _has_blacklisted_token(self, command: str, token: str) -> bool:
        low=command.lower()
        if token in {'>','>>','|',';','&&','`','$(','chmod 777'}:
            return token in low
        return re.search(r'(^|[^a-z0-9_-])' + re.escape(token) + r'($|[^a-z0-9_-])', low) is not None

    def check(self, command: str, allow_dangerous: bool=False) -> CommandResult:
        for bad in self.blacklist:
            if self._has_blacklisted_token(command, bad):
                return CommandResult(command=command, success=False, output=f'blocked blacklist keyword: {bad}', blocked=True)
        if any(command.startswith(d) for d in self.dangerous_legal):
            if allow_dangerous:
                return CommandResult(command=command, success=True, output='security check passed (rollback path)')
            if self.unattended_policy == 'deny':
                return CommandResult(command=command, success=False, output='blocked by unattended_policy=deny; route through the approval workflow', blocked=True)
            return CommandResult(command=command, success=False, output='requires human approval', requires_approval=True)
        if not any(re.match(p, command) for p in self.allow_patterns):
            return CommandResult(command=command, success=False, output='command not in whitelist', blocked=True)
        if 'cookie=' in command and not re.search(r'cookie=0x4e65744d[0-9a-fA-F]{8}', command):
            return CommandResult(command=command, success=False, output='invalid NetMind cookie', blocked=True)
        if 'tc ' in command and re.search(r'dev ([^\s]+)', command):
            dev=re.search(r'dev ([^\s]+)', command).group(1)
            if not re.match(r'^[sh][0-9]+-eth[0-9]+$', dev):
                return CommandResult(command=command, success=False, output='invalid interface for Mininet safety policy', blocked=True)
        return CommandResult(command=command, success=True, output='security check passed')

    def snapshot(self) -> dict:
        return {
            'allowlist': sorted({p.split()[0] for p in self.allow_patterns}),
            'deny_keywords': list(self.blacklist),
            'approval_required': list(self.dangerous_legal),
            'unattended_policy': self.unattended_policy,
        }

    def configure(self, payload: dict) -> dict:
        if isinstance(payload.get('deny_keywords'), list):
            self.blacklist=sorted(set(self.blacklist) | {str(k) for k in payload['deny_keywords']})
        if isinstance(payload.get('approval_required'), list):
            self.dangerous_legal=sorted(set(self.dangerous_legal) | {str(k) for k in payload['approval_required']})
        if payload.get('unattended_policy') in ('deny','approve'):
            self.unattended_policy=payload['unattended_policy']
        return self.snapshot()

SECURITY=SecurityChecker()
