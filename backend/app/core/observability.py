"""服务自身的可观测性。

项目能审计网络设备（netmind audit 巡检下游），却答不出客户关于**它自己**这条
服务的任何问题：活着吗、p99 多少、错误率多少、队列积压吗。商业部署时客户第一句
SLO 问题就卡在这里。

这里只做进程内、无依赖的采集——自托管工具不该为了「看自己」再拉一个 Prometheus
client 进来。指标以 JSON 暴露（人可读、也能被简单采集器抓走）。
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

STARTED_AT = time.time()

_lock = threading.Lock()
_counters: Dict[str, int] = defaultdict(int)
_timers: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=2048))


def inc(name: str, n: int = 1) -> None:
    with _lock:
        _counters[name] += n


def observe(name: str, seconds: float) -> None:
    with _lock:
        _timers[name].append(seconds)


def reset() -> None:
    """测试用。"""
    with _lock:
        _counters.clear()
        _timers.clear()


def _pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return round(s[k], 4)


def snapshot() -> dict:
    with _lock:
        timers = {k: list(v) for k, v in _timers.items()}
        counters = dict(_counters)
    lat = {}
    for k, vals in timers.items():
        if not vals:
            continue
        lat[k] = {
            'count': len(vals),
            'p50': _pct(vals, 0.50),
            'p95': _pct(vals, 0.95),
            'p99': _pct(vals, 0.99),
            'max': round(max(vals), 4),
        }
    return {
        'uptime_seconds': round(time.time() - STARTED_AT, 2),
        'pid': os.getpid(),
        'counters': counters,
        'latency_seconds': lat,
    }


class Timer:
    """上下文管理器：with Timer('api'): ..."""

    def __init__(self, name: str):
        self.name = name
        self.t0 = 0.0

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        observe(self.name, time.perf_counter() - self.t0)
        inc(self.name + '.calls')
        if exc and exc[0] is not None:
            inc(self.name + '.errors')
        return False
