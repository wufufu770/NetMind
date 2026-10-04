"""MCP stdio 服务的协议层。

`handle()` 是纯函数，所以这里不需要起子进程就能把协议全部覆盖——
这正是把它与 IO 循环分开的目的（测试协议却要 spawn 进程，是本末倒置）。

两条不能妥协的：
  · **stdio 不构成放宽执行的理由**：`tools/call` 默认 dry_run
  · **未注册/已禁用的工具照常拒绝**，不因为传输方式不同就放行
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import mcp_server
from app.mcp_server import (INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST,
                            METHOD_NOT_FOUND, PARSE_ERROR, handle, parse_line,
                            serve)


class _FakeMCP:
    def __init__(self, tools, result=None):
        self._tools = tools
        self._result = result or {'ok': True, 'echo': 'called'}
        self.calls = []

    def list_tools(self):
        return {'tools': self._tools}

    def call_tool(self, name, arguments=None, dry_run=True):
        self.calls.append((name, arguments, dry_run))
        return self._result


def _req(id_, method, **params):
    r = {'jsonrpc': '2.0', 'id': id_, 'method': method}
    if params:
        r['params'] = params
    return r


# ---------- 握手与清单 ----------

def test_initialize_reports_server_and_says_dry_run_is_the_default():
    r = handle(_req(1, 'initialize'))
    assert r['id'] == 1 and r['jsonrpc'] == '2.0'
    res = r['result']
    assert res['serverInfo']['name'] == 'netmind'
    assert res['capabilities']['tools'] is not None
    assert 'dry_run' in res['instructions'], \
        '必须在握手里说清默认干跑——客户端不该靠猜'


def test_tools_list_only_returns_enabled_tools():
    mcp = _FakeMCP([{'name': 'a', 'enabled': True},
                    {'name': 'b', 'enabled': False},
                    {'name': 'c', 'enabled': True}])
    r = handle(_req(2, 'tools/list'), mcp=mcp)
    names = [t['name'] for t in r['result']['tools']]
    assert names == ['a', 'c'], '禁用工具不该出现在清单里——客户端照着调必然失败'


def test_notification_gets_no_response():
    """notification 没有 id 就没有响应。回一条会让客户端困惑。"""
    assert handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None
    assert handle({'jsonrpc': '2.0', 'method': 'ping'}) is None


# ---------- 调用 ----------

def test_tools_call_defaults_to_dry_run():
    """stdio 不构成放宽执行的理由。"""
    mcp = _FakeMCP([])
    handle(_req(3, 'tools/call', name='ovs_tool', arguments={'a': 1}), mcp=mcp)
    assert mcp.calls == [('ovs_tool', {'a': 1}, True)], mcp.calls


def test_tools_call_can_opt_into_real_execution_explicitly():
    mcp = _FakeMCP([])
    handle(_req(4, 'tools/call', name='ovs_tool', arguments={}, dry_run=False), mcp=mcp)
    assert mcp.calls[0][2] is False, '显式 dry_run=false 才放行'


def test_tools_call_wraps_result_as_text_content():
    mcp = _FakeMCP([], result={'ok': True, 'stdout': 'hi'})
    r = handle(_req(5, 'tools/call', name='t', arguments={}), mcp=mcp)
    res = r['result']
    assert res['content'][0]['type'] == 'text'
    assert json.loads(res['content'][0]['text'])['stdout'] == 'hi'
    assert res.get('isError') is not True


def test_failed_call_is_marked_is_error():
    mcp = _FakeMCP([], result={'ok': False, 'error': 'tool not registered'})
    r = handle(_req(6, 'tools/call', name='nope', arguments={}), mcp=mcp)
    assert r['result']['isError'] is True, '工具失败必须标 isError，否则客户端以为成功了'


def test_unregistered_tool_is_still_refused():
    """不因为走 stdio 就放行。"""
    mcp = _FakeMCP([], result={'ok': False, 'error': 'tool not registered'})
    r = handle(_req(7, 'tools/call', name='ghost', arguments={}), mcp=mcp)
    assert r['result']['isError'] is True
    assert 'not registered' in r['result']['content'][0]['text']


# ---------- 协议错误 ----------

@pytest.mark.parametrize('bad, code', [
    (123, INVALID_REQUEST),                       # 不是对象
    ({'jsonrpc': '2.0', 'id': 1}, INVALID_REQUEST),  # 缺 method
    ({'jsonrpc': '2.0', 'id': 1, 'method': 42}, INVALID_REQUEST),  # method 非字符串
    (_req(1, '完全不存在的方法'), METHOD_NOT_FOUND),
])
def test_protocol_violations_get_standard_codes(bad, code):
    r = handle(bad)
    assert r['error']['code'] == code, r


def test_invalid_params_for_tools_call():
    for params in ({}, {'name': ''}, {'name': 42}, {'name': 't', 'arguments': 'x'}):
        r = handle(_req(1, 'tools/call', **params))
        assert r['error']['code'] == INVALID_PARAMS, f'{params} → {r}'


def test_params_must_be_object():
    r = handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': 'nope'})
    assert r['error']['code'] == INVALID_PARAMS


# ---------- 行解析与 IO 循环 ----------

def test_parse_error_is_still_a_wellformed_response():
    """坏输入也要回一条合规的 JSON-RPC 错误，而不是静默或崩。"""
    r = parse_line('{ not json')
    assert r['error']['code'] == PARSE_ERROR
    assert r['id'] is None
    json.dumps(r)          # 必须可序列化


def test_blank_lines_are_ignored():
    assert parse_line('') is None
    assert parse_line('   \n') is None


def test_serve_writes_one_response_per_request():
    lines = [json.dumps(_req(1, 'initialize')),
             json.dumps({'jsonrpc': '2.0', 'method': 'ping'}),   # notification
             json.dumps(_req(2, 'ping')),
             '',
             'garbage']
    out = io.StringIO()
    handled = serve(io.StringIO('\n'.join(lines) + '\n'), out)
    got = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    assert handled == 3, 'notification 不算、parse error 算'   # initialize, ping(id2), garbage
    assert [g['id'] for g in got] == [1, 2, None]


def test_serve_ends_when_stdin_closes():
    out = io.StringIO()
    assert serve(io.StringIO(''), out) == 0
    assert out.getvalue() == ''
