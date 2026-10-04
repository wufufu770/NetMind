#!/usr/bin/env python
"""在真实设备上验证 link_down 处置路径：诊断 → 下发路由 → 重测 →（没改善则回滚）。

诚实表此前把 link_down 标成「未在设备上实跑」——`ip route add` 这条处置命令
从生成到安全门到真下发，测试里都有，但**从没在真设备上跑通过整条**。
只在模拟器上验过的东西，证明不了它能落到设备上。

两个场景，都要设备侧独立证据（不采信 NetMind 自报）：

  A 修好了：备份路由指向真实网关 → 丢包 1.0 → 0.0 → success=True
  B 没修好：备份路由指向黑洞网关 → 丢包仍是 1.0 → 触发回滚，
            随后**读设备路由表**确认那条路由真的被撤下

场景 B 验的是轮 22 补的那条链路：回滚要过安全门，而 `ip route del` 属危险操作，
放行条件是「这条路由是本系统 add 下去的」（路由归属登记）。没有那次登记，
回滚会被安全门自己拦下——这种废回滚只在真撤销那一刻才暴露。

用法（实验台须已由 `scripts/lab.sh up` 起好）：

    NETMIND_DRIVER=ssh NETMIND_SSH_HOST=192.168.1.11 NETMIND_SSH_PORT=2222 \\
    NETMIND_SSH_USERNAME=netmind NETMIND_SSH_PASSWORD=netmind123 \\
    NETMIND_ENABLE_REAL_COMMANDS=true NETMIND_SUDO=true \\
    NETMIND_PROBE_TARGET=192.168.3.1 NETMIND_HEAL_IFACE=eth0 \\
    NETMIND_HEAL_BACKUP_ROUTE="192.168.3.0/24 via 192.168.1.2" \\
    .venv/bin/python scripts/verify_linkdown.py

注意 env 名是 NETMIND_SSH_USERNAME（不是 ..._USER）。写错不会静默失败——
快照的 source 会退回 simulated，本脚本据此退出非零。

退出码 0 = 两个场景都拿到设备侧证据；非零 = 验证不成立。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

REQUIRED = ('NETMIND_DRIVER', 'NETMIND_SSH_HOST', 'NETMIND_SSH_USERNAME',
            'NETMIND_SSH_PASSWORD', 'NETMIND_ENABLE_REAL_COMMANDS',
            'NETMIND_PROBE_TARGET', 'NETMIND_HEAL_IFACE', 'NETMIND_HEAL_BACKUP_ROUTE')
_missing = [k for k in REQUIRED if not os.environ.get(k)]
if _missing:
    sys.exit('缺少环境变量：' + ', '.join(_missing) +
             '\n这台脚本必须在真实设备上跑；让它在模拟器上跑等于什么都没验证。\n'
             '用法见本文件头部。')

IFACE = os.environ.get('NETMIND_HEAL_IFACE', 'eth0')
GOOD_ROUTE = os.environ['NETMIND_HEAL_BACKUP_ROUTE']
# 黑洞网关：路由加得上（语法合法、经安全门），但没人应答——正好造出「下发了却没改善」
BLACKHOLE_ROUTE = os.environ.get('NETMIND_VERIFY_BLACKHOLE_ROUTE',
                                 GOOD_ROUTE.split(' via ')[0] + ' via 192.168.1.99')
ROUTE_PREFIX = GOOD_ROUTE.split(' via ')[0].split()[0]

import paramiko                                              # noqa: E402
from app.core.telemetry import TELEMETRY, _real_snapshot     # noqa: E402

_fails: list[str] = []


def _ssh() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(os.environ['NETMIND_SSH_HOST'],
              int(os.getenv('NETMIND_SSH_PORT', '22')),
              os.environ['NETMIND_SSH_USERNAME'],
              os.environ['NETMIND_SSH_PASSWORD'], timeout=15)
    return c


def routes(ssh) -> str:
    _, out, _ = ssh.exec_command('ip route show')
    return out.read().decode().strip()


def clear(ssh) -> None:
    """把实验台恢复到起点。不留状态是刻意的——下次跑要能看到同样的起点。"""
    ssh.exec_command(f'sudo -n ip route del {ROUTE_PREFIX} via '
                     f'{GOOD_ROUTE.split(" via ")[1]} dev {IFACE}')[1].read()
    ssh.exec_command(f'sudo -n ip route del {BLACKHOLE_ROUTE} dev {IFACE}')[1].read()


def _probe() -> tuple:
    snap, why = _real_snapshot()
    if snap is None:
        sys.exit(f'真实探测失败，本轮验证作废（不能拿模拟器的数字当证据）：{why}')
    if str(snap.source) != 'real':
        sys.exit(f'快照来源是 {snap.source}，不是 real——设备没被真正问到')
    return snap


def scenario_fixed(ssh) -> bool:
    print('=== 场景 A：备份路由指向真实网关，应修好 ===')
    clear(ssh)
    snap = _probe()
    print(f'  起点: 丢包 {snap.packet_loss}  延迟 {snap.latency_ms}ms  source={snap.source}')
    d = TELEMETRY.diagnose([snap])
    print(f'  诊断: {d.type}  置信度 {d.confidence}')
    if d.type != 'link_down':
        _fails.append(f'诊断没判成 link_down（{d.type}），场景不成立')
        return False
    TELEMETRY._last_fallback = ''
    rep = TELEMETRY.heal(d)
    imp = rep.improvement
    print(f'  处置: {rep.action_taken}')
    print(f'  模式 {imp.get("deploy_mode")}  已下发到设备 {imp.get("applied")}')
    print(f'  丢包 {imp.get("loss_before")} → {imp.get("loss_after")}'
          f'  延迟 {imp.get("latency_before_ms")} → {imp.get("latency_after_ms")}ms')
    print(f'  success={rep.success} verified={rep.verified}')
    # 设备侧独立证据：路由表里真的有这条，且真的通了
    after = routes(ssh)
    on_device = ROUTE_PREFIX in after
    _, out, _ = ssh.exec_command(f'ping -c 3 -W 2 {os.environ["NETMIND_PROBE_TARGET"]} 2>&1 | tail -2')
    ping = out.read().decode().strip()
    print(f'  设备侧路由表: {after}')
    print(f'  设备侧连通性: {ping}')
    ok = (rep.success and rep.verified and imp.get('applied') is True
          and on_device and ' 0% packet loss' in ping)
    if not ok:
        _fails.append('场景 A：报告说修好了，但设备侧对不上'
                      f'（success={rep.success} applied={imp.get("applied")} '
                      f'路由在设备上={on_device}）')
    print(f'  >>> {"通过" if ok else "未通过"}')
    return ok


def scenario_not_fixed(ssh) -> bool:
    print('\n=== 场景 B：备份路由指向黑洞，应触发回滚并真撤下 ===')
    clear(ssh)
    os.environ['NETMIND_HEAL_BACKUP_ROUTE'] = BLACKHOLE_ROUTE
    snap = _probe()
    print(f'  起点: 丢包 {snap.packet_loss}  source={snap.source}')
    d = TELEMETRY.diagnose([snap])
    TELEMETRY._last_fallback = ''
    rep = TELEMETRY.heal(d)
    imp = rep.improvement
    rb = imp.get('rollback', {})
    print(f'  处置: {rep.action_taken}')
    # 注意这里 before 未必等于 1.0：场景 B 接着 A 跑，起点已是修好的状态，
    # 所以加黑洞路由往往让链路**变得更糟**（丢包 0.0 → 1.0）。那恰恰是更强的场景——
    # 回滚不只该在「没变化」时触发，也该在「主动造成退化」时触发。
    print(f'  丢包 {imp.get("loss_before")} → {imp.get("loss_after")}（未改善即应回滚）')
    print(f'  回滚: capability={rb.get("capability")} attempted={rb.get("attempted")} '
          f'rolled_back={rb.get("rolled_back")} complete={rb.get("complete")}')
    print(f'  success={rep.success}（没修好就不该报成功）')
    os.environ['NETMIND_HEAL_BACKUP_ROUTE'] = GOOD_ROUTE
    # 设备侧独立证据：黑洞路由不该还留在表里
    after = routes(ssh)
    print(f'  设备侧路由表: {after}')
    gone = ROUTE_PREFIX not in after
    ok = (rep.success is False
          and rb.get('capability') == 'inverse'
          and rb.get('rolled_back') is True
          and rb.get('complete') is True
          and gone)
    if not ok:
        _fails.append(f'场景 B：回滚未在设备上落实'
                      f'（success={rep.success} capability={rb.get("capability")} '
                      f'rolled_back={rb.get("rolled_back")} 设备上已撤={gone}）')
    print(f'  >>> {"通过" if ok else "未通过"}')
    return ok


def main() -> int:
    ssh = _ssh()
    try:
        start = routes(ssh)
        print(f'=== 设备 {os.environ["NETMIND_SSH_HOST"]} 起点路由表 ===\n{start}\n')
        a = scenario_fixed(ssh)
        b = scenario_not_fixed(ssh)
        clear(ssh)
    finally:
        try:
            ssh.close()
        except Exception:
            pass
    print()
    if _fails:
        print('>>> link_down 路径验证未通过：')
        for f in _fails:
            print(f'  - {f}')
        return 1
    print('>>> link_down 路径验证通过（两个场景都拿到设备侧证据）')
    return 0 if (a and b) else 1


if __name__ == '__main__':
    sys.exit(main())
