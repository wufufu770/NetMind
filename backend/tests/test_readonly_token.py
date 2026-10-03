"""只读凭据：能看，不能改。

SECURITY.md 此前明写「无 per-endpoint RBAC……没有只读角色」。对一个自托管
网络运维工具，最常见的实际需求恰恰是「让另一个人能看运行态势，但不许他
下发配置变更」——原先只有匿名只读（`NETMIND_ALLOW_ANON_READONLY`）或全权
token 两个极端，中间档缺失。

这里的凭据判定仍按方法而非按端点分权：只读凭据能过所有 GET/HEAD/OPTIONS，
被拒于所有写方法。真正的细粒度 RBAC（谁能碰哪台设备）不在本轮范围内。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.access import SAFE_METHODS, evaluate, verify_any

ADMIN = 'admin-secret'
RO = 'read-only-secret'


class _Req:
    def __init__(self, method, path, token=None, host='203.0.113.9'):
        self.method = method
        self.url = type('U', (), {'path': path})()
        self.headers = {'authorization': f'Bearer {token}'} if token else {}
        self.client = type('C', (), {'host': host})()


@pytest.fixture(autouse=True)
def _remote(monkeypatch):
    """这些用例都在测「远程访问」的判定。

    conftest 的 autouse fixture 会把 _client_host 打成 127.0.0.1，让业务测试
    不受认证门影响；那正好抹掉本文件要测的东西，所以这里显式改回远程地址。
    """
    import app.core.access as _access
    monkeypatch.setattr(_access, '_client_host', lambda request: '203.0.113.9')


@pytest.fixture
def tokens(monkeypatch):
    monkeypatch.setenv('NETMIND_ADMIN_TOKEN', ADMIN)
    monkeypatch.setenv('NETMIND_READONLY_TOKEN', RO)
    monkeypatch.delenv('NETMIND_ALLOW_ANON_READONLY', raising=False)
    monkeypatch.delenv('NETMIND_TRUST_PROXY', raising=False)


@pytest.mark.parametrize('method', sorted(SAFE_METHODS))
def test_readonly_token_may_read(tokens, method):
    d = evaluate(_Req(method, '/api/dashboard', RO))
    assert d.allowed is True, f'{method} 应被只读凭据放行'
    assert d.mode == 'readonly-token'


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
def test_readonly_token_cannot_write(tokens, method):
    """写操作是 403 而不是 401——凭据有效，只是权限不够。"""
    d = evaluate(_Req(method, '/api/telemetry/heal', RO))
    assert d.status == 403
    assert d.allowed is False


def test_admin_token_still_has_full_access(tokens):
    for method in ('GET', 'POST'):
        d = evaluate(_Req(method, '/api/dashboard', ADMIN))
        assert d.allowed is True, f'管理员凭据的 {method} 被拒了'


def test_wrong_token_is_401_not_403(tokens):
    """凭据错误与权限不足要能区分：前者是 401，客户端知道该换凭据。"""
    assert evaluate(_Req('GET', '/api/dashboard', 'nope')).status == 401
    assert evaluate(_Req('POST', '/api/telemetry/heal', 'nope')).status == 401


def test_readonly_token_survives_admin_token_rotation(tokens, monkeypatch):
    """换管理员 token 不该连带作废只读凭据——两者是独立发放的。"""
    monkeypatch.setenv('NETMIND_ADMIN_TOKEN', 'rotated')
    assert evaluate(_Req('GET', '/api/dashboard', RO)).allowed is True
    assert evaluate(_Req('GET', '/api/dashboard', 'rotated')).allowed is True


def test_identical_tokens_resolve_to_admin(tokens):
    """两个变量配成同一个值时，权限取高的那个。

    这是有意的：运维把两个变量填成同一串时，他要的是能写。
    另一种选择（取只读）会让配置看起来生效、实际什么都做不了。
    """
    tokens_env = dict(os.environ)
    os.environ['NETMIND_ADMIN_TOKEN'] = os.environ['NETMIND_READONLY_TOKEN'] = 'same'
    try:
        d = evaluate(_Req('POST', '/api/telemetry/heal', 'same'))
        assert d.allowed is True and d.mode == 'token'
    finally:
        os.environ.clear(); os.environ.update(tokens_env)


def test_empty_readonly_token_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv('NETMIND_ADMIN_TOKEN', ADMIN)
    monkeypatch.setenv('NETMIND_READONLY_TOKEN', '')
    d = evaluate(_Req('GET', '/api/dashboard', ADMIN))
    assert d.allowed is True and d.mode == 'token'


def test_readonly_only_deployment_allows_reads_but_no_writes(monkeypatch):
    """只配只读凭据 = 明确的只读部署，不是配置事故。"""
    monkeypatch.delenv('NETMIND_ADMIN_TOKEN', raising=False)
    monkeypatch.setenv('NETMIND_READONLY_TOKEN', RO)
    assert evaluate(_Req('GET', '/api/dashboard', RO)).allowed is True
    assert evaluate(_Req('POST', '/api/telemetry/heal', RO)).status == 403


def test_no_token_configured_still_means_loopback_only(monkeypatch):
    """加了这个功能不等于放松默认：什么都不配时远程依然 403。"""
    monkeypatch.delenv('NETMIND_ADMIN_TOKEN', raising=False)
    monkeypatch.delenv('NETMIND_READONLY_TOKEN', raising=False)
    d = evaluate(_Req('GET', '/api/dashboard'))
    assert d.allowed is False and d.status == 403


def test_public_paths_need_no_credential_at_all(tokens):
    for p in ('/healthz', '/docs', '/openapi.json'):
        assert evaluate(_Req('GET', p)).allowed is True, p


def test_verify_any_does_not_depend_on_candidate_order():
    """不短路是有意的：早退会让「命中第几个」体现在响应时间上。"""
    a = verify_any(f'Bearer {RO}', (('admin', 'a'), ('readonly', RO)))
    b = verify_any(f'Bearer {RO}', (('readonly', RO), ('admin', 'a')))
    assert a == b == 'readonly'
    assert verify_any('Bearer zzz', (('admin', 'a'), ('readonly', RO))) is None
    assert verify_any(f'not-bearer {RO}', (('readonly', RO),)) is None
    assert verify_any(None, (('readonly', RO),)) is None


def test_verify_any_skips_empty_candidates():
    assert verify_any(f'Bearer {RO}', (('admin', ''), ('readonly', RO))) == 'readonly'
    assert verify_any(f'Bearer {RO}', (('admin', ''), ('readonly', ''))) is None
