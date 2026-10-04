"""MCP stdio 服务：把工具注册表暴露成 JSON-RPC 2.0 over stdio。

此前只有 `MCPProtocol` 那个进程内 HTTP 适配器（`/api/mcp/*`），并不是真正的
MCP 服务——外部客户端按 MCP 协议连不上。本模块补上 stdio 传输：每个 stdin 行
一个 JSON-RPC 请求，每个 stdout 行一个 JSON-RPC 响应。

分两层是刻意的：
  · `handle()` 是**纯函数**，不碰 stdin/stdout，所以协议逻辑能被单元测试覆盖
  · `serve()` 只是 IO 循环，把行喂给 `handle()`——它唯一的作用就是把协议层
    和传输层分开，否则每次测协议都要起一个子进程

## 安全

走 stdio 不比走 HTTP 更可信、更不受限。本模块不做任何绕过：
  · `tools/call` **默认 dry_run**，与 HTTP 路径一致；要真执行必须在参数里显式写
    `dry_run: false`，而那仍受 `TOOLS.call` 自身的策略与审批门约束
  · 未注册/已禁用的工具照常拒绝，不因为是 stdio 就放行
  · `initialize` 之外的方法一律返回 Method not found，不做「宽容的猜测调用」
"""
from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO

from . import __version__
from .core.mcp_protocol import MCP

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

PROTOCOL_NAME = 'netmind'
PROTOCOL_VERSION = '1.0'


def _result(req_id: Any, result: Any) -> dict:
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def _error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {'code': code, 'message': message}
    if data is not None:
        err['data'] = data
    return {'jsonrpc': '2.0', 'id': req_id, 'error': err}


def _tool_entries(mcp: Any | None = None) -> list[dict]:
    """对外的工具清单。**只列已启用的工具**。

    stdio 客户端拿到清单就会照着调，列出禁用工具等于把「点了没反应」的
    失败提前推给调用方。这里如实只给能用的。

    `mcp` 必须能注入：原先这里直接用模块级单例，导致 `handle(mcp=...)`
    的注入在清单这一半没生效——协议层一半可测、一半不可测。
    """
    listing = (mcp or MCP).list_tools()
    enabled = [t for t in listing.get('tools', []) if t.get('enabled')]
    return enabled


def handle(req: Any, *, mcp: Any | None = None) -> dict | None:
    """处理一个 JSON-RPC 请求。返回响应；notification（无 id）返回 None。"""
    m = mcp or MCP

    if not isinstance(req, dict):
        return _error(None, INVALID_REQUEST, '请求必须是 JSON 对象')

    req_id = req.get('id')
    method = req.get('method')
    if not isinstance(method, str) or not method:
        return _error(req_id, INVALID_REQUEST, '缺少 method')

    # notification：没有 id 就没有响应，写回去只会让客户端困惑
    is_notification = 'id' not in req

    if method == 'initialize':
        payload = {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': PROTOCOL_NAME, 'version': __version__},
            # 说清楚默认干跑：客户端不该靠猜
            'instructions': (
                'tools/call 默认 dry_run=true，不会真的下发命令。'
                '确需执行时显式传 dry_run=false，且仍受工具自身的审批与安全策略约束。'
            ),
        }
    elif method in ('notifications/initialized', 'initialized'):
        return None
    elif method == 'tools/list':
        payload = {'tools': _tool_entries(m)}
    elif method == 'tools/call':
        params = req.get('params') or {}
        if not isinstance(params, dict):
            return _error(req_id, INVALID_PARAMS, 'params 必须是对象')
        name = params.get('name')
        if not isinstance(name, str) or not name:
            return _error(req_id, INVALID_PARAMS, '缺少 tools/call 的 name')
        args = params.get('arguments') or {}
        if not isinstance(args, dict):
            return _error(req_id, INVALID_PARAMS, 'arguments 必须是对象')
        # 默认干跑。stdio 不构成放宽的理由。
        dry_run = params.get('dry_run')
        dry_run = True if dry_run is None else bool(dry_run)
        out = m.call_tool(name, args, dry_run=dry_run)
        text = json.dumps(out, ensure_ascii=False, indent=2)
        payload = {'content': [{'type': 'text', 'text': text}],
                   'isError': not bool(out.get('ok', True))}
    elif method == 'ping':
        payload = {}
    else:
        if is_notification:
            return None
        return _error(req_id, METHOD_NOT_FOUND, f'不支持的方法: {method}')

    return None if is_notification else _result(req_id, payload)


def parse_line(line: str, **kw) -> dict | None:
    """一行 → 一个响应。解析失败也是一条合规的 JSON-RPC 错误响应。"""
    line = line.strip()
    if not line:
        return None
    try:
        req = json.loads(line)
    except json.JSONDecodeError as exc:
        return _error(None, PARSE_ERROR, f'JSON 解析失败: {exc}')
    return handle(req, **kw)


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None,
          *, mcp: Any | None = None) -> int:
    """stdio IO 循环。逐行读、逐行写。返回处理的请求数。"""
    src = stdin if stdin is not None else sys.stdin
    dst = stdout if stdout is not None else sys.stdout
    handled = 0
    for line in src:
        res = parse_line(line, mcp=mcp)
        if res is None:
            continue
        dst.write(json.dumps(res, ensure_ascii=False) + '\n')
        dst.flush()
        handled += 1
    return handled
