from __future__ import annotations
import re
from ..schemas import CommandResult

class SecurityChecker:
    blacklist=['rm','dd','mkfs','reboot','shutdown','poweroff','kill','pkill','chmod 777','wget','curl','>','>>','|',';','&&','`','$(']
    allow_patterns=[
        r'^ovs-ofctl (add-flow|del-flows|mod-flows|dump-flows|dump-ports) [a-zA-Z0-9_.:=,/-]+.*$',
        r'^ovs-vsctl (show|list-ports|list-ifaces).*$',
        r'^tc (qdisc|class|filter) (add|del|show).*$',
        r'^iptables (-A|-D|-I|-L|-F|-N) (INPUT|OUTPUT|FORWARD).*$',
        r'^ip (link set|addr add|addr del|route add|route del).*$',
        r'^ping -c ([1-9]|10) .+$',
        r'^iperf3 .+$'
    ]
    dangerous_legal=['ovs-ofctl del-flows s1','iptables -F FORWARD','iptables -F INPUT','iptables -F OUTPUT']

    def _has_blacklisted_token(self, command: str, token: str) -> bool:
        low=command.lower()
        if token in {'>','>>','|',';','&&','`','$(','chmod 777'}:
            return token in low
        return re.search(r'(^|[^a-z0-9_-])' + re.escape(token) + r'($|[^a-z0-9_-])', low) is not None

    def check(self, command: str) -> CommandResult:
        for bad in self.blacklist:
            if self._has_blacklisted_token(command, bad):
                return CommandResult(command=command, success=False, output=f'blocked blacklist keyword: {bad}', blocked=True)
        if any(command.startswith(d) for d in self.dangerous_legal):
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

SECURITY=SecurityChecker()
