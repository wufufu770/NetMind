from __future__ import annotations
import os
import re
from datetime import datetime
from ..store import STORE

"""只读巡检引擎 v1 —— 家用/小微企业路由器合规基线。

设计红线：
- 全部检查命令均为只读（READONLY_GUARD 强制，单元测试逐条断言）；
- 真实执行必须同时满足 NETMIND_ENABLE_REAL_COMMANDS=true 与已配置凭据，
  否则降级为模拟模式，结果显式标注 mode=simulated，不谎报。
"""


class ReadonlyViolation(Exception):
    pass


READONLY_GUARD = re.compile(
    r'^(ubus call |uci (-q )?(get|show) |cat /etc/|uname |ip (addr|link|route) show|'
    r'iptables (-L|-S)|nft list |ss -tln|netstat -tln|opkg list-installed|'
    r'dropbear -?\w|openssl version|logread \| tail)'
)


def _assert_readonly(commands: list[str]) -> None:
    for c in commands:
        if not READONLY_GUARD.match(c):
            raise ReadonlyViolation(f'非只读命令被拒绝: {c}')


def _eval_firmware(out: dict) -> dict:
    board = out.get('ubus call system board', '') or ''
    release = out.get('cat /etc/openwrt_release', '') or ''
    text = board + release
    version = ''
    m = re.search(r'(?:version|DISTRIB_RELEASE)["\'=:\s]+([0-9][0-9.\-a-zA-Z]*)', text)
    if m:
        version = m.group(1)
    return {'id': 'firmware', 'title': '固件/系统版本采集',
            'status': 'info', 'severity': 'info',
            'evidence': version or '未识别到版本串（人工核对）'}


def _eval_password_auth(out: dict) -> dict:
    v = (out.get('uci -q get dropbear.@dropbear[0].PasswordAuth', '') or '').strip()
    root_ok = 'on' in v.lower() or v == '1'
    return {'id': 'ssh_password_auth', 'title': 'SSH 口令登录状态',
            'status': 'warn' if root_ok else 'ok',
            'evidence': f'PasswordAuth={v or "未配置"}；建议仅密钥登录' if root_ok else f'PasswordAuth={v or "未配置"}'}


def _eval_upnp(out: dict) -> dict:
    v = (out.get('uci -q get upnpd.config.enabled', '') or '').strip()
    enabled = v == '1'
    return {'id': 'upnp', 'title': 'UPnP 状态',
            'status': 'warn' if enabled else 'ok',
            'evidence': f'upnpd.enabled={v or "0/未安装"}' + ('；UPnP 会自动打洞，暴露内网服务' if enabled else '')}


def _eval_firewall(out: dict) -> dict:
    rules = out.get('nft list ruleset | head -40', '') or out.get('iptables -L -n | head -40', '') or ''
    has_rules = bool(re.search(r'(chain \w+|Chain \w+)', rules)) and len(rules.strip().splitlines()) > 3
    return {'id': 'firewall_rules', 'title': '防火墙规则存在性',
            'status': 'warn' if not has_rules else 'ok',
            'evidence': f'{len(rules.strip().splitlines())} 行规则集样本'}


def _eval_listening_ports(out: dict) -> dict:
    ss = out.get('ss -tln', '') or out.get('netstat -tln', '') or ''
    risky = [p for p in ('23', '8080', ':80 ') if re.search(rf'[:.]({p.strip()})\s', ss)]
    telnet = ':23 ' in ss
    return {'id': 'listening_ports', 'title': '管理面监听端口',
            'status': 'fail' if telnet else ('warn' if risky else 'ok'),
            'evidence': f"命中管理端口: {','.join(risky)}" if risky else '未发现高危管理端口对外监听'}


def _eval_wireless(out: dict) -> dict:
    w = out.get('uci -q show wireless', '') or ''
    open_ifaces = re.findall(r"\.encryption='?none", w)
    return {'id': 'wireless_encryption', 'title': '无线加密强度',
            'status': 'fail' if open_ifaces else 'ok',
            'evidence': f'{len(open_ifaces)} 个开放(无加密)无线接口' if open_ifaces else '全部无线接口已启用加密'}


CHECKS = [
    {'id': 'firmware', 'title': '固件/系统版本采集', 'commands': [
        'ubus call system board', 'cat /etc/openwrt_release', 'uname -a'], 'eval': _eval_firmware},
    {'id': 'ssh_password_auth', 'title': 'SSH 口令登录状态', 'commands': [
        'uci -q get dropbear.@dropbear[0].PasswordAuth'], 'eval': _eval_password_auth},
    {'id': 'upnp', 'title': 'UPnP 状态', 'commands': [
        'uci -q get upnpd.config.enabled'], 'eval': _eval_upnp},
    {'id': 'firewall_rules', 'title': '防火墙规则存在性', 'commands': [
        'nft list ruleset | head -40', 'iptables -L -n | head -40'], 'eval': _eval_firewall},
    {'id': 'listening_ports', 'title': '管理面监听端口', 'commands': [
        'ss -tln', 'netstat -tln'], 'eval': _eval_listening_ports},
    {'id': 'wireless_encryption', 'title': '无线加密强度', 'commands': [
        'uci -q show wireless'], 'eval': _eval_wireless},
]

for c in CHECKS:  # 构造期即强制只读
    _assert_readonly(c['commands'])


SIMULATED_OUTPUTS = {
    'ubus call system board': '{"hostname":"HomeGW","model":"Xiaomi AX3000T","board_name":"xiaomi,ax3000t","release":{"distribution":"OpenWrt","version":"23.05.5"}}',
    'cat /etc/openwrt_release': 'DISTRIB_ID=\'OpenWrt\'\nDISTRIB_RELEASE=\'23.05.5\'\nDISTRIB_TARGET=\'ramips/mt7981\'',
    'uname -a': 'Linux HomeGW 5.15.167 #0 SMP Fri Sep 27 14:44:26 2024 aarch64 GNU/Linux',
    'uci -q get dropbear.@dropbear[0].PasswordAuth': 'on',
    'uci -q get upnpd.config.enabled': '1',
    'nft list ruleset | head -40': '\tchain input {\n\t\ttype filter hook input priority filter; policy accept;\n\t\tct state established,related accept\n\t\tiifname "wan" tcp dport 22 accept comment "SSH"\n\t}\n\tchain forward {\n\t\ttype filter hook forward priority filter; policy accept;\n\t}',
    'iptables -L -n | head -40': '',
    'ss -tln': 'Netid State Recv-Q Send-Q Local Address:Port\ntcp   LISTEN 0      128   0.0.0.0:22   0.0.0.0:*\ntcp   LISTEN 0      128   0.0.0.0:80   0.0.0.0:*\ntcp   LISTEN 0      64    0.0.0.0:8080 0.0.0.0:*',
    'netstat -tln': '',
    'uci -q show wireless': 'wireless.radio0=wifi-device\nwireless.default_radio0=wifi-iface\nwireless.default_radio0.encryption=\'psk2\'\nwireless.radio1=wifi-device\nwireless.guest_wifi=wifi-iface\nwireless.guest_wifi.encryption=\'none\'',
}

REAL_ALLOWED = {c for chk in CHECKS for c in chk['commands']}


def _real_exec() -> tuple[dict, str]:
    """真实只读执行：复用 netmiko 凭据体系。返回 (outputs, target)。"""
    host = os.getenv('NETMIND_SSH_HOST', '')
    if not os.getenv('NETMIND_ENABLE_REAL_COMMANDS', 'false').lower() == 'true':
        raise PermissionError('真实巡检需 NETMIND_ENABLE_REAL_COMMANDS=true')
    if not host or not os.getenv('NETMIND_SSH_USERNAME', ''):
        raise PermissionError('缺少 NETMIND_SSH_HOST / NETMIND_SSH_USERNAME')
    try:
        from netmiko import ConnectHandler
    except ImportError as exc:
        raise RuntimeError('需要 drivers 扩展: pip install -r requirements-drivers.txt') from exc
    conn = ConnectHandler(
        device_type=os.getenv('NETMIND_SSH_DEVICE_TYPE', 'linux'),
        host=host, port=int(os.getenv('NETMIND_SSH_PORT', '22')),
        username=os.getenv('NETMIND_SSH_USERNAME', ''),
        password=os.getenv('NETMIND_SSH_PASSWORD', ''),
    )
    outputs = {}
    try:
        for chk in CHECKS:
            for cmd in chk['commands']:
                _assert_readonly([cmd])
                try:
                    outputs[cmd] = conn.send_command(cmd, read_timeout=15) or ''
                except Exception as exc:
                    outputs[cmd] = f'<exec-error: {exc}>'
    finally:
        conn.disconnect()
    return outputs, host


def run_audit(mode: str | None = None, note: str | None = None) -> dict:
    want_real = (mode or os.getenv('NETMIND_AUDIT_MODE', '')).lower() == 'real'
    if want_real:
        outputs, target = _real_exec()
        used_mode = 'real'
    else:
        outputs, target, used_mode = SIMULATED_OUTPUTS, 'simulated-target', 'simulated'

    results = []
    for chk in CHECKS:
        try:
            r = chk['eval']({k: v for k, v in outputs.items()})
        except Exception as exc:
            r = {'id': chk['id'], 'title': chk['title'], 'status': 'error', 'evidence': str(exc)}
        r['commands'] = chk['commands']
        results.append(r)

    counts = {s: sum(1 for r in results if r['status'] == s) for s in ('ok', 'warn', 'fail')}
    report = {
        'audit_id': f"audit-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        'mode': used_mode,
        'target': target,
        'note': note,
        'checks': results,
        'summary': counts,
        'verdict': '发现风险项' if (counts['warn'] or counts['fail']) else '基线通过',
    }
    STORE.log('audit', f"{report['audit_id']} mode={used_mode} verdict={report['verdict']} "
                       f"(ok={counts['ok']} warn={counts['warn']} fail={counts['fail']})",
              'warn' if (counts['warn'] or counts['fail']) else 'info')
    return report


def render_markdown(report: dict) -> str:
    lines = [f"# NetMind 只读巡检报告 — {report['audit_id']}",
             f"- 目标: `{report['target']}`　模式: **{report['mode']}**　结论: **{report['verdict']}**",
             f"- 统计: ✅ {report['summary']['ok']}　⚠️ {report['summary']['warn']}　⛔ {report['summary']['fail']}", '']
    if report['mode'] == 'simulated':
        lines.append('> ⚠️ 本报告为**模拟数据**演练（未连接真实设备），用于演示与验证流程。')
        lines.append('')
    badge = {'ok': '✅', 'warn': '⚠️', 'fail': '⛔', 'error': '❓', 'info': 'ℹ️'}
    for r in report['checks']:
        lines.append(f"## {badge.get(r['status'], '•')} {r['title']} [{r['status']}]")
        lines.append(f"- 证据: {r.get('evidence', '-')}")
        lines.append(f"- 只读命令: {'; '.join('`' + c + '`' for c in r.get('commands', []))}")
        lines.append('')
    lines.append('_本报告由 netmind audit 自动生成；所有命令均为只读。_')
    return '\n'.join(lines)
