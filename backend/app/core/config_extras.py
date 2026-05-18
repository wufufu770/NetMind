
from __future__ import annotations
from typing import Dict, Any

SECURITY_CONFIG = {
    'allowlist': ['ovs-ofctl','ovs-vsctl','tc','iptables','ip','ping','iperf3'],
    'deny_keywords': ['rm','dd','mkfs','reboot','shutdown','poweroff','kill','pkill','chmod 777','wget','curl','>','>>','|',';','&&','`','$('],
    'approval_required': ['ovs-ofctl del-flows','iptables -F','tc qdisc del'],
    'unattended_policy': 'deny',
}
FONT_CONFIG = {
    'font_family': 'Inter, PingFang SC, Microsoft YaHei, sans-serif',
    'code_font_family': 'JetBrains Mono, SFMono-Regular, Consolas, monospace',
    'custom_font_url': '',
    'allow_upload': False,
}

def update_security(payload: Dict[str, Any]) -> Dict[str, Any]:
    SECURITY_CONFIG.update(payload)
    return SECURITY_CONFIG

def update_fonts(payload: Dict[str, Any]) -> Dict[str, Any]:
    FONT_CONFIG.update(payload)
    return FONT_CONFIG
