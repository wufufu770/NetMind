#!/usr/bin/env python
"""在真实设备上验证自愈闭环：注入 → 探测 → 诊断 → 下发 → 重测 → 读回。

与 `diagnose/closed_loop.py` 的 fixture 闭环不同，这里走的是主链路的
`TelemetryService.heal()`：处置是一条真命令，过安全门后经 TransactionManager
用 SSH 真实下发到设备，然后重测对比。

关键设计：注入点、探测点、下发点必须落在**同一台设备**上，否则延迟改善可能
来自别处，这次验证就什么也证明不了。

用法（实验台已由 scripts/lab.sh up 起好）：

    NETMIND_DRIVER=ssh NETMIND_SSH_HOST=192.168.1.11 NETMIND_SSH_PORT=2222 \\
    NETMIND_SSH_USERNAME=netmind NETMIND_SSH_PASSWORD=netmind123 \\
    NETMIND_ENABLE_REAL_COMMANDS=true NETMIND_SUDO=true \\
    NETMIND_PROBE_TARGET=192.168.1.30 .venv/bin/python scripts/verify_heal.py

注意 env 名是 NETMIND_SSH_USERNAME（不是 ..._USER）。写错不会静默失败——
安全连接会拒绝，快照 source 退回 simulated，本脚本据此退出非零。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# 探针与下发都要连设备，所以缺凭据时立刻退出，而不是让主链路降级到模拟器
# 继续跑出一份看着正常的假报告。
REQUIRED = ('NETMIND_DRIVER', 'NETMIND_SSH_HOST', 'NETMIND_SSH_USERNAME',
            'NETMIND_SSH_PASSWORD', 'NETMIND_ENABLE_REAL_COMMANDS',
            'NETMIND_PROBE_TARGET')
_missing = [k for k in REQUIRED if not os.environ.get(k)]
if _missing:
    sys.exit('缺少环境变量：' + ', '.join(_missing) +
             '\n这台脚本必须在真实设备上跑；让它在模拟器上跑等于什么都没验证。\n'
             '用法见本文件头部。')

IFACE = os.environ.get('NETMIND_VERIFY_IFACE', 'eth0')
DELAY = os.environ.get('NETMIND_VERIFY_DELAY_MS', '150ms')
LOSS = os.environ.get('NETMIND_VERIFY_LOSS', '10%')

from app.core.telemetry import TELEMETRY            # noqa: E402
from app.core.telemetry import _real_snapshot      # noqa: E402


def qdisc_state(ssh) -> str:
    _, out, _ = ssh.exec_command(f'sudo -n tc qdisc show dev {IFACE}')
    return out.read().decode().strip()


def main() -> int:
    import paramiko
    host = os.environ['NETMIND_SSH_HOST']
    port = int(os.environ.get('NETMIND_SSH_PORT', '22'))
    user = os.environ['NETMIND_SSH_USERNAME']
    pw = os.environ['NETMIND_SSH_PASSWORD']

    scenario = ('rollback'
                if '--scenario' in sys.argv
                and sys.argv[sys.argv.index('--scenario') + 1] == 'rollback'
                else 'heal')

    print(f'=== 0. 连设备 {host}:{port}（场景：{scenario}）===')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, port, user, pw, timeout=15)
    except Exception as exc:
        sys.exit(f'连不上设备 {host}:{port} — {type(exc).__name__}: {exc}')
    # 先清一次，避免上一轮遗留的 qdisc 让这次「注入」名不副实
    ssh.exec_command(f'sudo -n tc qdisc del dev {IFACE} root')[1].read()
    return _scenario_rollback(ssh) if scenario == 'rollback' else _scenario_heal(ssh)


def _scenario_rollback(ssh) -> int:
    """验证「下发成功但没改善 → 真回滚」这条路径。

    选 anomaly_traffic 而不是 congestion：它的处置是**加**一条限速，逆操作
    就是删掉它，等量可逆，所以回滚效果能在设备上直接读回。congestion 删的是
    设备原有整形，处置前没记参数就撤不回来——那条路径验的是「如实说撤不回来」。

    这里不注入故障：5mbit 限速对 ICMP 往返几乎无影响，所以重测不会改善，
    正好走到回滚分支。指标是真测的，不是编的。
    """
    from app.schemas import Diagnosis

    print('=== 1. 干净起点 ===')
    print(f'  设备侧 qdisc: {qdisc_state(ssh)}')
    snap, why = _real_snapshot()
    if snap is None:
        sys.exit(f'真实探测失败，本轮验证作废：{why}')
    print(f'  探测: {snap.latency_ms}ms 丢包 {snap.packet_loss} source={snap.source}')

    print('\n=== 2. heal()：下发限速 → 重测无改善 → 应触发回滚 ===')
    TELEMETRY._last_fallback = ''
    rep = TELEMETRY.heal(Diagnosis(type='anomaly_traffic', confidence=0.8),
                         iface=IFACE, rate_mbps=5)
    imp = rep.improvement
    rb = imp.get('rollback', {})
    print(f'  处置命令: {rep.action_taken}')
    print(f'  下发模式: {imp.get("deploy_mode")}  已下发到设备: {imp.get("applied")}')
    print(f'  延迟 {imp.get("latency_before_ms")}→{imp.get("latency_after_ms")}ms')
    print(f'  success={rep.success}  verified={rep.verified}')
    print(f'  回滚: capability={rb.get("capability")} attempted={rb.get("attempted")} '
          f'rolled_back={rb.get("rolled_back")} complete={rb.get("complete")}')
    print(f'  {rep.summary}')

    print('\n=== 3. 设备侧读回：回滚后限速应当已被撤销 ===')
    after_q = qdisc_state(ssh)
    print(f'  {after_q}')
    undone = 'netem' not in after_q
    print(f'\n>>> 回滚路径: {"通过" if undone else "未通过"}'
          f'（设备已恢复={undone}, 回滚完整={rb.get("complete")}）')
    return 0 if undone else 1


def _scenario_heal(ssh) -> int:
    ssh.exec_command(f'sudo -n tc qdisc add dev {IFACE} root netem delay {DELAY} loss {LOSS}')[1].read()
    print(f'  设备侧 qdisc: {qdisc_state(ssh)}')

    print('\n=== 1. 真实探测 ===')
    snap, why = _real_snapshot()
    if snap is None:
        sys.exit(f'真实探测失败，本轮验证作废（不能拿模拟器的数字当证据）：{why}')
    print(f'  延迟 {snap.latency_ms}ms  丢包 {snap.packet_loss}  source={snap.source}')

    print('\n=== 2. 诊断 ===')
    d = TELEMETRY.diagnose([snap])
    print(f'  {d.type}  置信度={d.confidence}  证据={d.evidence}')
    if d.type != 'congestion':
        sys.exit(f'注入 {DELAY} 延迟后诊断没判成 congestion，验证不成立：{d.type}')

    print('\n=== 3. heal()：生成 → 过安全门 → 真下发 → 重测 ===')
    rep = TELEMETRY.heal(d, iface=IFACE)
    imp = rep.improvement
    print(f'  处置命令: {rep.action_taken}')
    print(f'  下发模式: {imp.get("deploy_mode")}  下发成功: {imp.get("deploy_success")}')
    print(f'  延迟 {imp.get("latency_before_ms")}→{imp.get("latency_after_ms")}ms')
    print(f'  success={rep.success}  verified={rep.verified}')
    print(f'  {rep.summary}')

    print('\n=== 4. 设备侧读回（独立于 NetMind 自报的第三份证据）===')
    after_q = qdisc_state(ssh)
    print(f'  {after_q}')
    cleared = 'netem' not in after_q

    ok = rep.success and rep.verified and cleared
    print(f'\n>>> 真实闭环: {"通过" if ok else "未通过"}'
          f'（设备已清除={cleared}, success={rep.success}, verified={rep.verified}）')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
