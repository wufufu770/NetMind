"""面板与复核接口的诚实性回归。

此前 `/api/dashboard` 的数字是写死的路由常量（`sla: 98`、`active_intents: 2`，
外加三条固定的风险文案和两个编造的意图名），`/api/system/ai-recovery-review`
则永远返回「复核完成、无冲突」而什么都没比较。诚实表里没有对应条目声明这些
是模拟的——对以「不编数据」为纪律的项目来说，这是最该先拆的一处。

前端同源问题一并覆盖：健康分曾在 sla 为空时用丢包率反推 96/82，
下发/回滚结果里写过 `sla_feasible: true`、`sla_confidence: 1`。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.dashboard import build_dashboard
from app.schemas import TelemetrySnapshot


# ---------- 纯函数 ----------

def test_empty_state_yields_no_invented_numbers():
    """空状态下面板不能有任何编出来的数字。"""
    d = build_dashboard(executions=[], telemetry=[], logs=[], topology=None)
    assert d['metrics']['latency_ms'] is None
    assert d['metrics']['packet_loss'] is None
    assert d['metrics']['active_intents'] == 0
    assert d['risks'] == [], '没有观测却凭空生成了风险条目'
    assert d['active_intents'] == []


def test_sla_is_never_computed_without_a_target():
    """SLA 达成率需要事先约定的 SLO 目标；项目里没有，就不该有这个数。

    这是本组测试里最要紧的一条：`sla` 曾经是写死的 98，而 98 这个数字
    会被直接当成「实测达成率」读。
    """
    for telemetry in ([], [TelemetrySnapshot(latency_ms=0.1, packet_loss=0.0,
                                              throughput_mbps=900, alert=False,
                                              source='real')]):
        d = build_dashboard(executions=[], telemetry=telemetry, logs=[], topology=None)
        assert d['metrics']['sla'] is None
        assert d['provenance']['sla_computed'] is False
        assert d['metrics']['sla_reason']


def test_risks_only_appear_when_observations_support_them():
    quiet = build_dashboard(
        executions=[],
        telemetry=[TelemetrySnapshot(latency_ms=0.2, packet_loss=0.0, throughput_mbps=80,
                                     alert=False, source='real')],
        logs=[], topology=None)
    assert quiet['risks'] == [], '健康的真实遥测不该被编成风险'

    noisy = build_dashboard(
        executions=[],
        telemetry=[TelemetrySnapshot(latency_ms=180.0, packet_loss=0.3, throughput_mbps=5,
                                     alert=True, source='real')],
        logs=[], topology=None)
    titles = ' '.join(r['title'] for r in noisy['risks'])
    assert '180.0ms' in titles, '风险条目里应能读回触发它的那个数值'
    assert all('evidence' in r for r in noisy['risks']), '每条风险都要能追溯到证据'


def test_every_risk_carries_its_evidence():
    d = build_dashboard(
        executions=[],
        telemetry=[TelemetrySnapshot(latency_ms=99.0, packet_loss=0.1, throughput_mbps=1,
                                     alert=True, source='real')],
        logs=[], topology=None)
    for r in d['risks']:
        assert r['evidence'], f'风险 {r["title"]} 没有证据字段'


def test_active_intents_come_from_real_executions():
    from app.schemas import Execution, Status
    ex = Execution(execution_id='e-1', intent_text='给会议网提高优先级', status=Status.running)
    done = Execution(execution_id='e-2', intent_text='访客限速', status=Status.success)
    d = build_dashboard(executions=[ex, done], telemetry=[], logs=[], topology=None)
    assert d['metrics']['active_intents'] == 1
    assert [i['execution_id'] for i in d['active_intents']] == ['e-1']
    assert d['active_intents'][0]['title'] == '给会议网提高优先级'


# ---------- 端点 ----------

@pytest.fixture
def local_client(monkeypatch):
    import app.core.access as _access
    from fastapi.testclient import TestClient
    from app.main import app
    from app.store import STORE
    monkeypatch.setattr(_access, '_client_host', lambda request: '127.0.0.1')
    for k in ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_TRUST_PROXY'):
        monkeypatch.delenv(k, raising=False)
    STORE.executions.clear(); STORE.telemetry.clear(); STORE.logs.clear()
    with TestClient(app) as c:
        yield c


def test_dashboard_endpoint_reports_null_sla_not_a_number(local_client):
    d = local_client.get('/api/dashboard').json()
    assert d['metrics']['sla'] is None
    assert d['metrics']['sla_reason']


def test_dashboard_endpoint_reflects_recorded_telemetry(local_client):
    from app.store import STORE
    STORE.record_telemetry(TelemetrySnapshot(latency_ms=42.5, packet_loss=0.001,
                                             throughput_mbps=88, alert=False, source='real'))
    d = local_client.get('/api/dashboard').json()
    assert d['metrics']['latency_ms'] == 42.5
    assert d['provenance']['telemetry_source'] == 'real'


def test_ai_recovery_review_returns_a_real_verdict(local_client):
    """复核要有判定字段，不能只有一句写死的「无冲突」。"""
    r = local_client.post('/api/system/ai-recovery-review').json()
    assert r['verdict'] in ('differences-found', 'no-difference', 'partial', 'indeterminate')
    assert 'compared' in r and 'undecidable' in r
    # 无可比对的记录时不能报「无冲突」
    assert r['verdict'] == 'indeterminate' or r['compared'] > 0
    assert r['verdict'] == 'indeterminate', '空 store 下不得声称「无冲突」'


def test_ai_recovery_review_flags_undeterminable_entries(local_client, monkeypatch):
    """比对跑不了就是跑不了，要记进 undecidable 而不是算作「一致」。"""
    from app.schemas import Execution, Status
    from app.store import STORE
    STORE.executions['e-x'] = Execution(execution_id='e-x', intent_text='某意图',
                                        status=Status.success)
    import app.core.workflow as wf
    monkeypatch.setattr(wf.ORCHESTRATOR, 'parse_intent_with_agent',
                        lambda text: (_ for _ in ()).throw(RuntimeError('no model')))
    r = local_client.post('/api/system/ai-recovery-review').json()
    assert r['compared'] == 0
    assert r['undecidable'], '无法判定的执行没有记下来'
    assert r['verdict'] in ('partial', 'indeterminate')
    assert '无冲突' not in r['message'] or r['compared'] > 0


# ---------- WebSocket 连接清理 ----------

def test_websocket_is_removed_from_registry_on_error(local_client, monkeypatch):
    """发送过程中抛错也必须把连接摘掉。

    原实现只捕 `WebSocketDisconnect`，任何其他异常都会让控制流直接穿出函数，
    连接永远留在 `WS` 列表里——而 `/api/system/status` 正是拿 `len(WS)` 当
    「在线客户端数」报的。长跑进程里客户端反复重连，这个列表只增不减。
    """
    from app.core.telemetry import TELEMETRY
    from app.realtime import WS

    def boom(*a, **kw):
        raise RuntimeError('probe exploded')

    monkeypatch.setattr(TELEMETRY, 'sample', boom)
    with pytest.raises(Exception):
        with local_client.websocket_connect('/ws/events'):
            pass
    assert len(WS) == 0, f'异常路径下连接泄漏，WS 里还剩 {len(WS)} 个'


def test_websocket_connects_and_streams(local_client):
    """正常路径下确实能连上并收到遥测帧——不是只有清理逻辑。"""
    from app.realtime import WS
    with local_client.websocket_connect('/ws/events') as ws:
        frame = ws.receive_json()
        assert frame['type'] == 'telemetry'
        assert 'data' in frame
        assert len(WS) >= 1
    assert len(WS) == 0, '正常断开后应清空登记'


# ---------- SLA 预测：判定必须跟着给的目标走 ----------

def _fill_latency(values):
    from app.store import STORE
    STORE.telemetry.clear()
    for v in values:
        STORE.record_telemetry(TelemetrySnapshot(latency_ms=v, packet_loss=0.001,
                                                 throughput_mbps=90, alert=False,
                                                 source='real'))


def test_sla_verdict_follows_the_supplied_target(local_client):
    """同一份观测，换个目标就该换结论。

    原实现把门槛写死成 50ms，调用方传的目标从未被读取——那不是「预测」，
    是「拿一个固定阈值对任意业务下结论」。
    """
    _fill_latency([180, 190, 175])
    strict = local_client.post('/api/telemetry/predict-sla',
                               json={'sla': {'latency_ms': 50}}).json()
    assert strict['feasible'] is False
    assert strict['target_used']['latency_ms'] == 50

    relaxed = local_client.post('/api/telemetry/predict-sla',
                                json={'sla': {'latency_ms': 400}}).json()
    assert relaxed['feasible'] is True, '把目标放宽到 400ms 后仍判不可行——门槛写死了'
    assert relaxed['average_latency_ms'] == strict['average_latency_ms'], '两次的观测应相同'


def test_sla_without_target_reaches_no_verdict(local_client):
    """没给目标就不得下「可行/不可行」——那是替用户决定什么叫达标。"""
    _fill_latency([10, 12, 11])
    r = local_client.post('/api/telemetry/predict-sla', json={}).json()
    assert r['feasible'] is None
    assert r['verdict'] == 'no-target-provided'
    assert r['message']


def test_sla_breaches_name_the_metric_and_both_numbers(local_client):
    _fill_latency([180, 190, 175])
    r = local_client.post('/api/telemetry/predict-sla',
                          json={'sla': {'latency_ms': 50, 'packet_loss': 0.01}}).json()
    b = r['breaches']
    assert len(b) == 1 and b[0]['metric'] == 'latency_ms'
    assert b[0]['observed'] > b[0]['target']


def test_sla_endpoint_accepts_post(local_client):
    """前端一直发的是 POST；原实现是 GET，实测直接 405。"""
    _fill_latency([10])
    assert local_client.post('/api/telemetry/predict-sla', json={}).status_code == 200


def test_sla_result_is_json_serialisable_even_without_history(local_client):
    from app.store import STORE
    STORE.telemetry.clear()
    r = local_client.post('/api/telemetry/predict-sla',
                          json={'sla': {'latency_ms': 50}}).json()
    assert isinstance(r['window'], int)
    assert 'measurement_sources' in r
