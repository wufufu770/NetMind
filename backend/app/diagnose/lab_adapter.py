"""把闭环接到真实实验台（scripts/lab.sh 起的 docker 拓扑）。

本模块只做 I/O 适配：真的调 tc / ip link、真的 ping。
判断逻辑在 closed_loop.py，数据解析在 lab_collector.py，三者职责不混。
"""
from __future__ import annotations

import subprocess

from .closed_loop import run_closed_loop
from .lab_collector import collect_lab_snapshot
from ..schemas import Diagnosis, HealingReport

R1 = 'nm-r1'
R2 = 'nm-r2'


def _sh(container: str, cmd: str) -> str:
    r = subprocess.run(['docker', 'exec', container, 'sh', '-c', cmd],
                       capture_output=True, text=True, timeout=30)
    return (r.stdout or '') + (r.stderr or '')


def inject_congestion(delay_ms: int = 120, loss: str = '8%', rate: str | None = None) -> str:
    """真注入：给 r1 出口挂 netem。delay 必带，rate 可选（不带就是「延迟升高但带宽未降」）。"""
    spec = f'netem delay {delay_ms}ms loss {loss}'
    if rate:
        spec += f' rate {rate}'
    _sh(R1, f'tc qdisc replace dev eth1 root {spec}')
    return f'r1 eth1 注入 {spec}'


def inject_link_down() -> str:
    _sh(R2, 'ip link set eth1 down')
    return 'r2 eth1 link down'


def clear_fault() -> str:
    out = []
    _sh(R1, 'tc qdisc del dev eth1 root 2>/dev/null')
    out.append('清除 r1 出口 qdisc')
    _sh(R2, 'ip link set eth1 up 2>/dev/null')
    out.append('恢复 r2 eth1 up')
    return '；'.join(out)


# 处置动作：把故障真的修掉
ACTIONS = {
    'congestion': lambda: clear_fault(),
    'link_down': lambda: clear_fault(),
    'anomaly_traffic': lambda: clear_fault(),
    'config_error': lambda: clear_fault(),
    'normal': lambda: '无需动作',
}


def run_lab_loop(baseline_throughput_mbps: float | None = 21.08,
                 count: int = 10) -> HealingReport:
    """完整闭环跑在真实验台上。measure/act 都是真动作，不是模拟。"""
    def measure() -> dict:
        return collect_lab_snapshot(count=count)

    def act(d: Diagnosis) -> str:
        return ACTIONS.get(d.type, clear_fault)()

    def rollback() -> str:
        return '注入的故障未能靠 clear 消除，需人工介入'

    return run_closed_loop(measure=measure, act=act, rollback=rollback,
                           baseline_throughput_mbps=baseline_throughput_mbps)
