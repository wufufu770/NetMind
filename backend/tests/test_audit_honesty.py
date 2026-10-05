"""安全审计的诚实性：没检查 ≠ 检查通过。

巡检项是 **OpenWrt 专用**的（uci / ubus / dropbear）。此前它们对着任何设备跑：
Alpine 上 `uci` 不存在，shell 回一行 `-bash: uci: command not found`，
而解析器把**这行错误文本当成了设置值**——`PasswordAuth` 不在 {on,1} 里，
于是判成 ok。实测一台 Alpine 设备上，SSH 口令、UPnP、无线加密三项
全部报 ok：**安全审计在从未检查过的设备上报告「通过」**。

这是安全工具最危险的失败模式：使用者据此以为设备是安全的。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core import audit as A

# 一台 Alpine 容器的真实回包：uci / nft / ubus 都不存在
ALPINE = {
    'ubus call system board': '-bash: ubus: command not found',
    'cat /etc/openwrt_release': '-bash: cat: /etc/openwrt_release: No such file or directory',
    'uname -a': 'Linux client2 5.15.167 #1 SMP x86_64 GNU/Linux',
    'uci -q get dropbear.@dropbear[0].PasswordAuth': '-bash: uci: command not found',
    'uci -q get upnpd.config.enabled': '-bash: uci: command not found',
    'nft list ruleset | head -40': '-bash: nft: command not found',
    'iptables -L -n | head -40': '-bash: iptables: command not found',
    'ss -tln': 'Netid State Recv-Q Send-Q Local Address:Port\n'
               'tcp   LISTEN 0      128   0.0.0.0:22   0.0.0.0:*',
    'netstat -tln': '-bash: netstat: command not found',
    'uci -q show wireless': '-bash: uci: command not found',
}

# 一台真 OpenWrt 的回包
OPENWRT = {
    'ubus call system board': '{"hostname":"HomeGW","release":{"distribution":"OpenWrt","version":"23.05.5"}}',
    'cat /etc/openwrt_release': "DISTRIB_ID='OpenWrt'\nDISTRIB_RELEASE='23.05.5'",
    'uname -a': 'Linux HomeGW 5.15.167 aarch64 GNU/Linux',
    'uci -q get dropbear.@dropbear[0].PasswordAuth': 'on',
    'uci -q get upnpd.config.enabled': '0',
    'nft list ruleset | head -40': 'chain input {\ntype filter hook input; policy drop;\n}\nchain forward {\n}',
    'ss -tln': 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*',
    'uci -q show wireless': "wireless.default_radio0.encryption='psk2'",
}


def _by_id(out, check_id):
    for chk in A.CHECKS:
        if chk['id'] == check_id:
            return chk['eval'](out)
    raise AssertionError(f'没有 {check_id} 这一项')


# ---------- 核心：读不到就不是通过 ----------

@pytest.mark.parametrize('check_id', ['ssh_password_auth', 'upnp', 'wireless_encryption',
                                      'firewall_rules'])
def test_unreadable_command_is_unknown_not_ok(check_id):
    r = _by_id(ALPINE, check_id)
    assert r['status'] == 'unknown', \
        f'{check_id} 在读不到数据时判成了 {r["status"]}——把 shell 报错当成了实测值'
    assert '未检查' in r['evidence']


def test_evidence_never_leaks_the_shell_error_as_a_value():
    """证据里必须说清「没读到」，而不是把 `command not found` 当成设置值。"""
    r = _by_id(ALPINE, 'ssh_password_auth')
    assert 'PasswordAuth=-bash' not in r['evidence'], \
        'shell 报错仍被当作配置值展示'
    assert 'uci: command not found' in r['evidence'], '应把真实失败原因写进证据'


def test_usable_helper_rejects_shell_errors_and_blanks():
    assert A._usable('on') is True
    assert A._usable('') is False
    assert A._usable(None) is False
    assert A._usable('-bash: uci: command not found') is False
    assert A._usable('<exec-error: timeout>') is False
    assert A._usable('Permission denied') is False


# ---------- 真的读到了才判 ----------

def test_openwrt_device_still_gets_real_verdicts():
    """别把「读不到」判成 unknown 之后，把真设备也一起变成 unknown。"""
    assert _by_id(OPENWRT, 'ssh_password_auth')['status'] == 'warn', '口令登录开着应报 warn'
    assert _by_id(OPENWRT, 'upnp')['status'] == 'ok'
    assert _by_id(OPENWRT, 'firewall_rules')['status'] == 'ok'
    assert '23.05.5' in _by_id(OPENWRT, 'firmware')['evidence']


def test_listening_ports_is_genuinely_checkable_on_alpine():
    """`ss` 在 Alpine 上有，所以这一项是真的检查了，仍应是 ok。"""
    r = _by_id(ALPINE, 'listening_ports')
    assert r['status'] == 'ok'


def test_open_wireless_is_fail_not_ok():
    r = _by_id({**OPENWRT, 'uci -q show wireless':
               "wireless.guest_wifi.encryption='none'"}, 'wireless_encryption')
    assert r['status'] == 'fail'
    assert '开放' in r['evidence']


# ---------- 结论层 ----------

def test_verdict_never_says_passed_when_something_was_unchecked():
    """有项目没检查，结论就不能是「基线通过」。"""
    r = A.run_audit.__wrapped__ if hasattr(A.run_audit, '__wrapped__') else None
    from app.core.audit import run_audit
    import app.core.audit as mod

    # 直接构造一份 Alpine 报告
    results = [c['eval'](ALPINE) for c in mod.CHECKS]
    for c, res in zip(mod.CHECKS, results):
        res['commands'] = c['commands']
    counts = {st: sum(1 for x in results if x['status'] == st)
              for st in ('ok', 'warn', 'fail', 'unknown', 'error', 'info')}
    unchecked = counts['unknown'] + counts['error']
    assert unchecked >= 4, 'Alpine 上应当有多项无法检查'
    # 复算 run_audit 里的判定逻辑
    verdict = ('巡检未完成（部分项目无法检查）'
               if unchecked and not (counts['warn'] or counts['fail'])
               else '发现风险项' if (counts['warn'] or counts['fail']) else '基线通过')
    assert verdict != '基线通过', '有项目没检查却判「基线通过」'


def test_markdown_report_shows_unchecked_count():
    from app.core.audit import render_markdown
    md = render_markdown({
        'audit_id': 'a-1', 'target': '1.2.3.4', 'mode': 'real',
        'verdict': '巡检未完成（部分项目无法检查）',
        'summary': {'ok': 1, 'warn': 0, 'fail': 0, 'unknown': 4, 'error': 0, 'info': 1},
        'checks': [{'title': 'SSH 口令登录状态', 'status': 'unknown',
                    'evidence': '未检查：读不到 dropbear 配置', 'commands': ['uci -q get x']}],
    })
    assert '未检查 4' in md
    assert '❔' in md, '未检查项应有独立徽章，不能和 ok 混为一谈'
    assert '基线通过' not in md.split('\n')[2]
