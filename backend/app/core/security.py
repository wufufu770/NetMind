from __future__ import annotations
import os
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
        # 语义级危险操作：按操作类型判定，与目标设备名无关。
        # mod-flows 可重写流表；ip link set down / route del / addr del 可致业务中断。
        self.dangerous_ops=[
            re.compile(r'^ovs-ofctl\s+del-flows\b'),
            re.compile(r'^ovs-ofctl\s+mod-flows\b'),
            re.compile(r'^iptables\s+-F\b'),
            re.compile(r'^ip\s+link\s+set\s+\S+\s+down\b'),
            re.compile(r'^ip\s+route\s+del\b'),
            re.compile(r'^ip\s+addr\s+del\b'),
        ]
        # 兼容入口：运维可通过 configure() 追加额外前缀（精确前缀匹配）。
        self.dangerous_legal=[]
        self.unattended_policy='deny'

    def _has_blacklisted_token(self, command: str, token: str) -> bool:
        low=command.lower()
        if token in {'>','>>','|',';','&&','`','$(','chmod 777'}:
            return token in low
        return re.search(r'(^|[^a-z0-9_-])' + re.escape(token) + r'($|[^a-z0-9_-])', low) is not None

    def _dangerous_target(self, command: str) -> str:
        parts=command.split()
        return parts[2] if len(parts) > 2 else 'unknown-target'

    def _is_dangerous(self, command: str) -> bool:
        if any(p.match(command) for p in self.dangerous_ops):
            return True
        return any(command.startswith(d) for d in self.dangerous_legal)

    def _has_owned_cookie(self, command: str) -> bool:
        """命令携带的 NetMind cookie 必须是系统登记签发过的（格式 + 登记双校验）。

        仅校验格式不够：0x4e65744d 前缀可从源码推知，攻击者或 LLM 幻觉可伪造
        「自有规则」的回滚命令。登记表由 TransactionManager 在部署时写入。
        """
        if not re.search(r'cookie=0x4e65744d[0-9a-fA-F]{8}', command):
            return False
        from ..store import STORE  # 延迟导入避免环
        return STORE.has_flow_cookie(command)

    def check(self, command: str, allow_dangerous: bool=False) -> CommandResult:
        for bad in self.blacklist:
            if self._has_blacklisted_token(command, bad):
                return CommandResult(command=command, success=False, output=f'blocked blacklist keyword: {bad}', blocked=True)
        if self._is_dangerous(command):
            target=self._dangerous_target(command)
            if allow_dangerous:
                # 回滚路径只对携带合法 NetMind cookie 的命令放行（证明回滚的是本系统下发的规则），
                # 其余一律照常走审批门禁，防止 LLM 生成的回滚命令夹带高危操作。
                if self._has_owned_cookie(command):
                    return CommandResult(command=command, success=True, output=f'security check passed (rollback of NetMind-owned rule on {target})')
            if self.unattended_policy == 'deny':
                return CommandResult(command=command, success=False, output=f'blocked by unattended_policy=deny ({target}); route through the approval workflow', blocked=True)
            return CommandResult(command=command, success=False, output=f'requires human approval: dangerous op on {target}', requires_approval=True)
        if not any(re.match(p, command) for p in self.allow_patterns):
            return CommandResult(command=command, success=False, output='command not in whitelist', blocked=True)
        if 'cookie=' in command and not re.search(r'cookie=0x4e65744d[0-9a-fA-F]{8}', command):
            return CommandResult(command=command, success=False, output='invalid NetMind cookie', blocked=True)
        if 'tc ' in command and re.search(r'dev ([^\s]+)', command):
            dev=re.search(r'dev ([^\s]+)', command).group(1)
            if self._real_mode():
                if not re.match(r'^[A-Za-z0-9@._:-]+$', dev):
                    return CommandResult(command=command, success=False, output='invalid interface name for real-device policy', blocked=True)
            elif not re.match(r'^[sh][0-9]+-eth[0-9]+$', dev):
                return CommandResult(command=command, success=False, output='invalid interface for Mininet safety policy', blocked=True)
        return CommandResult(command=command, success=True, output='security check passed')

    def _real_mode(self) -> bool:
        driver=os.getenv('NETMIND_DRIVER','simulation').lower()
        return driver in ('ssh','netconf') and os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false').lower() == 'true'

    def snapshot(self) -> dict:
        return {
            'allowlist': sorted({p.split()[0] for p in self.allow_patterns}),
            'deny_keywords': list(self.blacklist),
            'approval_required': [p.pattern for p in self.dangerous_ops] + list(self.dangerous_legal),
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
