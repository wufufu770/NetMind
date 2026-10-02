"""按来源的速率限制（进程内令牌桶，零外部依赖）。

SECURITY.md 此前自认「无速率限制」。对外暴露时这是真缺口：一个失控的脚本
或误配的循环能把设备打满，而 NetMind 每次 intent 提交都可能触发真实下发。

刻意不引 slowapi/limits 之类依赖——自托管工具的部署摩擦要尽量低。代价是
**限流状态只在进程内**：多 worker 部署下每个 worker 各有一份桶，实际阈值
会放大到 worker 数倍。这一条必须写进部署文档，不能埋着。
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

# 端点分组：写操作与「可能触发下发」的读操作收紧，纯读放宽
WRITE_LIMITS = {'per_second': 5.0, 'burst': 10}
SIDE_EFFECT_LIMITS = {'per_second': 10.0, 'burst': 20}
READ_LIMITS = {'per_second': 50.0, 'burst': 100}
PUBLIC_LIMITS = {'per_second': 5.0, 'burst': 10}     # /healthz 这类探活

BUCKETS = {
    'write': WRITE_LIMITS,
    'side_effect': SIDE_EFFECT_LIMITS,
    'read': READ_LIMITS,
    'public': PUBLIC_LIMITS,
}

SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=256))
_override = None      # 测试用；None 表示听环境的


def enabled() -> bool:
    """限流是否生效。

    刻意**每次判定时读环境变量**，而不是在模块导入时读一次。
    导入期改模块全局状态会产生顺序依赖：谁先导入谁说了算，测试里
    表现为「同一份代码有时限流有时不限流」——实测过，很难查。
    """
    if _override is not None:
        return _override
    v = os.getenv('NETMIND_RATE_LIMIT', 'on').strip().lower()
    return v not in ('off', 'false', '0', 'no')


def reset() -> None:
    with _lock:
        _hits.clear()


def set_enabled(v: bool | None) -> None:
    """测试与紧急停用。传 None 表示交回给环境变量。"""
    global _override
    _override = None if v is None else bool(v)


def classify(method: str, path: str) -> str:
    if path.startswith(('/healthz', '/docs', '/openapi.json', '/redoc')):
        return 'public'
    m = (method or '').upper()
    if m in SAFE_METHODS:
        return 'read'
    if m in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return 'write'
    return 'read'


def allow(key: str, group: str, now: float | None = None) -> tuple[bool, dict]:
    """令牌桶判定。返回 (放行?, 限额信息)。"""
    if not enabled():
        return True, {'group': group, 'limited': False}
    cfg = BUCKETS.get(group, READ_LIMITS)
    rate, burst = float(cfg['per_second']), float(cfg['burst'])
    t = now if now is not None else time.monotonic()
    with _lock:
        q = _hits[(key, group)]
        while q and t - q[0] >= 1.0:
            q.popleft()
        if len(q) >= burst:
            retry = max(0.0, 1.0 - (t - q[0])) if q else 1.0
            return False, {'group': group, 'limited': True,
                           'limit': rate, 'burst': burst,
                           'retry_after': round(retry + 0.05, 2)}
        q.append(t)
    return True, {'group': group, 'limited': False, 'limit': rate, 'burst': burst}


def reset_all() -> None:
    reset()
    set_enabled(None)      # 交回环境变量，不留测试残留
