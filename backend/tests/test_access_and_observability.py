"""默认安全与自身可观测性的回归。

这两条是「能不能交给别人自部署长期跑」的地基：
  · 默认不安全 = 别人一装上就裸奔，端口通就能读走全部拓扑与遥测
  · 无自身可观测 = 客户问一句 p99 就答不上来

原来的 auth_gate：token 为空则完全不认证，且 GET/HEAD/OPTIONS 永久豁免。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core import observability as obs
from app.core.access import (PUBLIC_PATHS, AuthDecision, decide, evaluate,
                             is_loopback, verify_token)


# ---------- 默认安全 ----------

def test_no_token_means_loopback_only_not_open():
    """没配 token 不是「不认证」而是「只许本机」——静默裸奔是最坏的一种不安全。"""
    d = decide('GET', '/api/telemetry/latest', '203.0.113.9', '')
    assert d.allowed is False and d.status == 403
    assert 'NETMIND_ADMIN_TOKEN' in d.reason, '拒绝时要告诉运维怎么修'


def test_no_token_allows_localhost():
    assert decide('GET', '/api/telemetry/latest', '127.0.0.1', '').allowed is True
    assert decide('GET', '/api/telemetry/latest', '::1', '').allowed is True
    assert decide('GET', '/api/telemetry/latest', '::ffff:127.0.0.1', '').allowed is True


def test_no_token_blocks_writes_even_locally_from_remote():
    d = decide('POST', '/api/experiment/fault', '203.0.113.9', '')
    assert d.allowed is False


def test_token_set_requires_auth_for_get_too():
    """原实现把 GET 永久豁免——token 设了也读得到全部运行数据。"""
    d = decide('GET', '/api/telemetry/latest', '203.0.113.9', 's3cret')
    assert d.allowed is False and d.status == 401


def test_anon_readonly_is_opt_in():
    assert decide('GET', '/api/telemetry/latest', '203.0.113.9', '',
                  allow_anon_readonly=False).allowed is False
    assert decide('GET', '/api/telemetry/latest', '203.0.113.9', '',
                  allow_anon_readonly=True).allowed is True
    # 只读豁免不能顺带放行写操作
    assert decide('POST', '/api/experiment/fault', '203.0.113.9', '',
                  allow_anon_readonly=True).allowed is False


def test_healthz_public_but_metrics_not():
    assert decide('GET', '/healthz', '203.0.113.9', 's3cret').allowed is True
    assert decide('GET', '/metrics', '203.0.113.9', 's3cret').allowed is False


def test_is_loopback_rejects_spoofable_forms():
    assert is_loopback('127.0.0.1') is True
    assert is_loopback('127.1.2.3') is True
    assert is_loopback('192.168.1.10') is False
    assert is_loopback('10.0.0.1') is False
    assert is_loopback('') is False
    assert is_loopback(None) is False


@pytest.fixture
def real_host(monkeypatch):
    """撤掉 conftest 的「视作本机」补丁，让这些用例能测真实对端判定。"""
    import app.core.access as acc
    real = acc._client_host
    monkeypatch.setattr(acc, '_client_host', real)
    # conftest 用 monkeypatch 改过，这里直接恢复模块里的原始函数
    import importlib
    importlib.reload(acc)
    yield


def test_x_forwarded_for_not_trusted_by_default(real_host):
    """没显式声明可信代理时不能拿 XFF 判 loopback——那个头可伪造。"""
    import app.core.access as acc
    class R:
        method = 'GET'
        url = type('U', (), {'path': '/api/telemetry/latest'})()
        headers = {'x-forwarded-for': '127.0.0.1'}
        client = type('C', (), {'host': '203.0.113.9'})()
    os.environ.pop('NETMIND_TRUST_PROXY', None)
    d = acc.evaluate(R())
    assert d.allowed is False, '伪造 XFF 不该骗过认证门'

    os.environ['NETMIND_TRUST_PROXY'] = 'true'
    try:
        assert acc.evaluate(R()).allowed is True, '显式信任代理后应采信 XFF'
    finally:
        os.environ.pop('NETMIND_TRUST_PROXY', None)


def test_verify_token_is_constant_time_and_rejects_junk():
    assert verify_token('Bearer s3cret', 's3cret') is True
    assert verify_token('Bearer s3cret ', 's3cret') is True
    assert verify_token('bearer s3cret', 's3cret') is False   # 前缀大小写敏感
    assert verify_token('s3cret', 's3cret') is False
    assert verify_token(None, 's3cret') is False
    assert verify_token('Bearer x', '') is False


# ---------- 端到端：HTTP 行为 ----------

@pytest.fixture
def client_factory():
    from fastapi.testclient import TestClient
    def make(host, token=None, anon_readonly=False, trust_proxy=None):
        for k, v in (('NETMIND_ADMIN_TOKEN', token),
                     ('NETMIND_ALLOW_ANON_READONLY', anon_readonly),
                     ('NETMIND_TRUST_PROXY', trust_proxy)):
            os.environ.pop(k, None)
            if v is not None:
                # os.environ 只收 str——bool 直接塞会 TypeError
                os.environ[k] = 'true' if v is True else str(v)
        import importlib
        import app.core.access as acc
        importlib.reload(acc)          # 恢复被 conftest 改掉的 _client_host
        from app import main
        importlib.reload(main)
        return TestClient(main.app, client=(host, 1234))
    yield make
    for k in ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_TRUST_PROXY'):
        os.environ.pop(k, None)


def test_remote_is_locked_down_by_default(client_factory, real_host):
    c = client_factory('203.0.113.9')
    assert c.get('/api/telemetry/latest').status_code == 403
    assert c.post('/api/experiment/fault', json={'kind': 'congestion'}).status_code == 403
    assert c.get('/healthz').status_code == 200


def test_token_enables_remote_with_correct_credential(client_factory, real_host):
    c = client_factory('203.0.113.9', token='s3cret')
    assert c.get('/api/telemetry/latest').status_code == 401
    assert c.get('/api/telemetry/latest', headers={'Authorization': 'Bearer s3cret'}).status_code == 200
    assert c.get('/api/telemetry/latest', headers={'Authorization': 'Bearer nope'}).status_code == 401


# ---------- 自身可观测性 ----------

def test_healthz_reports_uptime_and_version():
    from app.core.observability import STARTED_AT
    import time
    snap = obs.snapshot()
    assert snap['uptime_seconds'] >= 0
    assert snap['pid'] == os.getpid()
    assert STARTED_AT <= time.time()


def test_metrics_records_latency_and_counters():
    obs.reset()
    with obs.Timer('test.op'):
        pass
    s = obs.snapshot()
    assert s['counters']['test.op.calls'] == 1
    lat = s['latency_seconds']['test.op']
    assert lat['count'] == 1
    assert lat['p99'] is not None and lat['p99'] >= 0
    obs.reset()


def test_timer_counts_errors():
    obs.reset()
    try:
        with obs.Timer('fail.op'):
            raise ValueError('x')
    except ValueError:
        pass
    assert obs.snapshot()['counters']['fail.op.errors'] == 1
    obs.reset()


def test_metrics_endpoint_requires_auth_but_healthz_does_not(client_factory, real_host):
    c = client_factory('203.0.113.9', token='s3cret')
    assert c.get('/healthz').status_code == 200
    r = c.get('/metrics', headers={'Authorization': 'Bearer s3cret'})
    assert r.status_code == 200
    body = r.json()
    assert 'latency_seconds' in body and 'counters' in body
