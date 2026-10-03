"""认证与访问控制的判定逻辑。

从 main.py 里抽成纯函数是为了可测——这些判断决定了「谁能读写设备配置」，
不能只靠起个服务点两下来验证。

设计取向：**默认安全**。
  · 没配 token 时不是「不认证」，而是「只许本机」——静默裸奔是最坏的一种不安全。
  · 配了 token 时所有方法都要认证，包括 GET。只读匿名必须显式开。
  · 免认证的白名单只有健康检查与 API 文档。
  · 比对用常数时间，避免时序侧信道。
"""
from __future__ import annotations

import hmac
import os
import socket
from dataclasses import dataclass

# 免认证路径。/healthz 给容器与负载均衡探活用；文档路径本身不含运行数据。
PUBLIC_PATHS = frozenset({'/healthz', '/docs', '/openapi.json', '/redoc',
                          '/docs/oauth2-redirect'})

SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    status: int
    reason: str
    mode: str          # loopback-only | token | readonly-token | anon-readonly


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip()
    if h.startswith('::ffff:'):        # IPv4-mapped IPv6
        h = h[7:]
    if h in ('127.0.0.1', '::1', 'localhost'):
        return True
    return h.startswith('127.')


def _client_host(request) -> str | None:
    """取直连对端地址。

    刻意**不**信任 X-Forwarded-For：没配可信代理时它可被伪造，
    拿它判 loopback 等于把认证门敞开。反代场景应走 NETMIND_TRUST_PROXY 才读它。
    """
    if not request:
        return None
    if os.getenv('NETMIND_TRUST_PROXY', '').lower() == 'true':
        fwd = request.headers.get('x-forwarded-for')
        if fwd:
            return fwd.split(',')[0].strip()
        real = request.headers.get('x-real-ip')
        if real:
            return real.strip()
    client = getattr(request, 'client', None)
    return getattr(client, 'host', None) or (socket.gethostname() if client is None else None)


def decide(method: str, path: str, client_host: str | None,
           token: str, allow_anon_readonly: bool = False) -> AuthDecision:
    """核心判定。纯函数，不碰环境变量与请求对象。"""
    if path in PUBLIC_PATHS:
        return AuthDecision(True, 200, '公开路径', 'public')

    # 配了 token：一律要认证，含 GET。只读匿名必须显式开。
    if token:
        return AuthDecision(False, 401, '需要有效的 Bearer token', 'token')

    # 没配 token：不是「不认证」，而是「只许本机」
    if is_loopback(client_host):
        return AuthDecision(True, 200, '本机访问且未配置 token', 'loopback-only')
    if allow_anon_readonly and method.upper() in SAFE_METHODS:
        return AuthDecision(True, 200, '显式开启匿名只读', 'anon-readonly')
    return AuthDecision(False, 403,
                        '未配置 NETMIND_ADMIN_TOKEN，仅允许本机访问。'
                        '远程访问请设置该环境变量（生产部署必须设置）', 'loopback-only')


def verify_token(provided: str | None, expected: str) -> bool:
    """常数时间比对。token 非空才比。"""
    if not expected:
        return False
    if not provided:
        return False
    if not provided.startswith('Bearer '):
        return False
    return hmac.compare_digest(provided[7:].strip(), expected)


def verify_any(provided: str | None, candidates: tuple) -> str | None:
    """在多个候选凭据里找出命中的是哪个，全家桶返回。

    **不短路**：每个候选都比一遍再返回。早退会让「匹配到第几个」体现在响应
    时间上——攻击者据此区分凭据种类，甚至缩小爆破范围。只读凭据与管理员
    凭据权限不同，能区分出来本身就是可利用的信息。
    """
    if not provided or not provided.startswith('Bearer '):
        return None
    got = provided[7:].strip()
    hit = None
    for name, expected in candidates:
        if not expected:
            continue
        ok = hmac.compare_digest(got, expected)
        if ok and hit is None:
            hit = name
    return hit


def evaluate(request) -> AuthDecision:
    """从请求解析出判定。中间件用这个。"""
    token = os.getenv('NETMIND_ADMIN_TOKEN', '').strip()
    readonly = os.getenv('NETMIND_READONLY_TOKEN', '').strip()
    anon_read = os.getenv('NETMIND_ALLOW_ANON_READONLY', 'false').lower() == 'true'
    path = request.url.path

    if token or readonly:
        if path in PUBLIC_PATHS:
            return AuthDecision(True, 200, '公开路径', 'public')
        which = verify_any(request.headers.get('authorization'),
                           (('admin', token), ('readonly', readonly)))
        if which == 'admin':
            return AuthDecision(True, 200, '管理员凭据有效', 'token')
        if which == 'readonly':
            # 只读凭据配了不等于可以写：403 而非 401——凭据有效，只是权限不够
            if request.method.upper() in SAFE_METHODS:
                return AuthDecision(True, 200, '只读凭据有效且为安全方法', 'readonly-token')
            return AuthDecision(
                False, 403,
                '只读凭据不得执行写操作。读接口（GET/HEAD/OPTIONS）不受限；'
                '需要下发或变更请改用 NETMIND_ADMIN_TOKEN', 'readonly-token')
        return AuthDecision(False, 401, '需要有效的 Bearer token', 'token')

    host = _client_host(request)
    d = decide(request.method, path, host, '', anon_read)
    return d
