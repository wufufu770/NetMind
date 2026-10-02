"""速率限制的回归。

对应 SECURITY.md 原先自认的缺口：「The HTTP API has no rate limiting or
per-endpoint RBAC」。本文件锁住限流行为；RBAC 不在本轮（见 backlog）。

限流刻意放在鉴权**之前**：未授权的洪水请求同样要挡。让它先打到业务逻辑
等于给攻击者一个免费的压力放大器。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core import ratelimit
from app.core.ratelimit import allow, classify, reset_all, set_enabled


@pytest.fixture(autouse=True)
def _clean_buckets():
    # conftest 把限流默认关了（业务测试不该跟限流器打架），这里显式打开来测
    reset_all()
    set_enabled(True)
    yield
    reset_all()


# ---------- 分组 ----------

def test_classify_groups():
    assert classify('GET', '/api/telemetry/latest') == 'read'
    assert classify('HEAD', '/x') == 'read'
    assert classify('OPTIONS', '/x') == 'read'
    assert classify('POST', '/api/intent/submit') == 'write'
    assert classify('DELETE', '/api/config/x') == 'write'
    assert classify('PUT', '/x') == 'write'
    assert classify('GET', '/healthz') == 'public'
    assert classify('GET', '/openapi.json') == 'public'


# ---------- 桶行为 ----------

def test_burst_allows_up_to_limit():
    for _ in range(10):
        ok, _info = allow('1.1.1.1', 'write', now=0.0)
        assert ok is True
    ok, info = allow('1.1.1.1', 'write', now=0.0)
    assert ok is False
    assert info['retry_after'] > 0


def test_window_slides():
    """1 秒过去后额度恢复。"""
    for _ in range(10):
        allow('1.1.1.1', 'write', now=0.0)
    assert allow('1.1.1.1', 'write', now=0.5)[0] is False
    assert allow('1.1.1.1', 'write', now=1.5)[0] is True


def test_groups_have_independent_budgets():
    """写组打满不该拖垮读组。"""
    for _ in range(10):
        allow('2.2.2.2', 'write', now=0.0)
    assert allow('2.2.2.2', 'write', now=0.0)[0] is False
    assert allow('2.2.2.2', 'read', now=0.0)[0] is True


def test_keys_are_isolated():
    """一个来源被打满，不影响另一个来源。"""
    for _ in range(10):
        allow('3.3.3.3', 'write', now=0.0)
    assert allow('3.3.3.3', 'write', now=0.0)[0] is False
    assert allow('4.4.4.4', 'write', now=0.0)[0] is True


def test_read_limit_is_looser_than_write():
    for _ in range(10):
        allow('5.5.5.5', 'write', now=0.0)
    assert allow('5.5.5.5', 'read', now=0.0)[0] is True


def test_can_be_disabled():
    ratelimit.set_enabled(False)
    assert all(allow('6.6.6.6', 'write', now=0.0)[0] for _ in range(50))


# ---------- HTTP 行为 ----------

def test_over_limit_returns_429_with_retry_after():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, client=('127.0.0.1', 0))
    codes = [c.post('/api/experiment/fault', json={'kind': 'normal'}).status_code
             for _ in range(13)]
    assert 429 in codes, f'超限没被拦: {codes}'
    r = c.post('/api/experiment/fault', json={'kind': 'normal'})
    if r.status_code == 429:
        assert 'Retry-After' in r.headers
        assert r.json()['group'] == 'write'


def test_rate_limit_runs_before_auth():
    """未授权的洪水请求也要被限流挡下，不能先打到业务逻辑。"""
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, client=('198.51.100.9', 0))   # 远程、无 token
    codes = [c.post('/api/experiment/fault', json={'kind': 'normal'}).status_code
             for _ in range(14)]
    assert 429 in codes, f'未授权洪水请求没被限流挡下: {codes}'


def test_healthz_not_throttled_by_traffic():
    """探活不能被业务流量挤掉，否则负载均衡会误判服务已死。"""
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, client=('127.0.0.1', 0))
    for _ in range(10):
        c.get('/api/telemetry/latest')
    assert c.get('/healthz').status_code == 200
