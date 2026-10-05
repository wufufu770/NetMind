"""live 采集的两个诚实性问题。

## 1) 端口从不透传 —— live 采集只能连 22

`_collect_live` 有 `ssh_port: int = 22` 形参，而 `diagnose()` **从不传它**。
于是无论 `NETMIND_SSH_PORT` 设成什么，采集都打 22 端口。
实测：把实验台设备映射到 2222 端口，采集前一律 `[]`（全部超时失败），
修后采到 `['r2']`。**`diagnose --live` 对任何非 22 端口的设备完全不可用。**

## 2) 「没请求」与「请求了但失败」混为一谈

`checks.py` 在 `collected` 为空时一律写
"Live collection skipped (no device access requested)" —— 但实况是
**访问请求过了、失败了**。使用者会去查参数，而不会去查连接。
同理 `engine.py` 把逐节点的失败原因丢掉，只留一句
"live collection failed for all nodes"。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.diagnose import checks as C

# 拓扑路径必须相对**本文件**，不是 cwd。CI 的 pytest 步骤 working-directory
# 是 backend/，从仓库根跑能过、从 backend/ 跑就 FileNotFoundError。
# 这已经是同一个坑第三次（先在 test_real_telemetry.py、再在门禁探针里）。
# 门禁 `tests-are-reproducible` 会按 CI 的 cwd 再跑一遍来兜住它。
TOPO_YML = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'examples', 'clab-broken.yml')


TOPO = {'name': 't', 'nodes': {'a': {'id': 'a', 'kind': 'linux', 'mgmt': '1.2.3.4/24'}},
        'links': []}


def test_diagnose_accepts_and_uses_ssh_port(monkeypatch):
    """端口必须能从 env 或参数传下去。"""
    import inspect
    from app.diagnose import engine
    assert 'ssh_port' in inspect.signature(engine.diagnose).parameters, \
        'diagnose() 没有 ssh_port 形参——live 采集只能连默认 22'
    src = inspect.getsource(engine.diagnose)
    assert 'ssh_port=_port' in src or 'ssh_port=' in src, \
        'diagnose() 拿到了端口却没传给 _collect_live'


def test_diagnose_reads_port_from_env(monkeypatch):
    """不显式传参时也要读 NETMIND_SSH_PORT——设了却不用是最坑的形态。"""
    from app.diagnose import engine
    seen = {}

    def fake_collect(parsed, host_map, user, pwd, ssh_port=22):
        seen['port'] = ssh_port
        return None, ['x: y']
    monkeypatch.setattr(engine, '_collect_live', fake_collect)
    monkeypatch.setenv('NETMIND_SSH_PORT', '2222')
    engine.diagnose(TOPO_YML, live=True, host_map={'r2': '1.1.1.1'},
                    ssh_user='u', ssh_password='p')
    assert seen.get('port') == 2222, f'端口没被读进去（拿到 {seen.get("port")}）'


def test_per_node_failure_reasons_survive_into_notes(monkeypatch):
    """逐节点原因被丢掉 = 使用者只能自己猜。"""
    from app.diagnose import engine
    monkeypatch.setattr(engine, '_collect_live',
                        lambda p, h, u, pw, ssh_port=22: (None, ['r1: 超时', 'r2: 认证失败']))
    r = engine.diagnose(TOPO_YML, live=True, host_map={'r1': '1.1.1.1'},
                        ssh_user='u', ssh_password='p')
    notes = ' '.join(r.get('notes') or [])
    assert 'r1' in notes and 'r2' in notes, f'逐节点原因没进 notes: {r.get("notes")}'
    assert '超时' in notes and '认证失败' in notes


def test_report_distinguishes_not_requested_from_attempted():
    """「请求了但没采到」不该写成「没请求」。"""
    from app.diagnose.engine import diagnose
    import app.diagnose.engine as engine_mod
    orig = engine_mod._collect_live
    engine_mod._collect_live = lambda p, h, u, pw, ssh_port=22: (None, ['r2: 超时'])
    try:
        r = diagnose(TOPO_YML, live=True, host_map={'r2': '1.1.1.1'},
                     ssh_user='u', ssh_password='p')
    finally:
        engine_mod._collect_live = orig
    skip = next(f for f in r['findings'] if f['id'] == 'collection-skipped')
    assert 'no device access requested' not in skip['title'], \
        f'明明请求过却说没请求: {skip["title"]}'
    assert 'attempted' in skip['title'] or 'no data' in skip['title']
