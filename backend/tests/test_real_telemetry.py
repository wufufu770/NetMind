"""主链路真实遥测的回归。

两轮实测的收获，都固化在这里：

1. **模拟器永远测不到的区间**。旧 diagnose 规则里 `loss >= 5%` 返回 link_down，
   而模拟器的拥塞态丢包只有 1.8%，落在 5% 以下——所以那条分支从未被触发过。
   真实探测一上来就是 120ms + 10% 丢包，当场判成 link_down（错，应为 congestion）。
   断链是 >= 90% 丢包，5%~90% 是「劣化」，两者不是一回事。

2. **置信度必须随数据来源打折**。拿硬编码常量得出的判断不该有高置信度。

测试不依赖 docker：真实报文用 fixture，SSH 用假连接。
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core import telemetry as tel
from app.core.telemetry import (LATENCY_DEGRADED_MS, LOSS_DEGRADED, LOSS_LINK_DOWN,
                                TELEMETRY, _confidence, _real_snapshot)
from app.diagnose.lab_collector import classify, parse_ping, to_snapshot
from app.schemas import TelemetrySnapshot

FIXTURES = os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'fixtures', 'lab')


# ---------- 真实报文解析 ----------

def test_real_captures_parse_to_expected_states():
    for name, expect in (('ping-healthy', 'healthy'),
                         ('ping-congestion', 'congested'),
                         ('ping-link_down', 'link_down')):
        with open(os.path.join(FIXTURES, f'{name}.txt'), encoding='utf-8') as fh:
            m = parse_ping(fh.read())
        assert classify(m) == expect, f'{name} 应判为 {expect}，实际 {classify(m)}'


def test_missing_rtt_is_none_not_zero():
    """断链时 ping 根本不打印 round-trip 行。填 0 会被读成「零延迟健康链路」。"""
    with open(os.path.join(FIXTURES, 'ping-link_down.txt'), encoding='utf-8') as fh:
        m = parse_ping(fh.read())
    assert m['has_rtt'] is False
    assert m['rtt_avg_ms'] is None
    snap = to_snapshot(m, source='real')
    assert snap.packet_loss == 1.0


# ---------- 判据：断链 vs 劣化 ----------

def test_degraded_loss_is_congestion_not_link_down():
    """5%~90% 丢包 = 链路劣化（congestion），不是链路断开。

    这条正是模拟器测不到、真实数据一上来就判错的那个区间。
    """
    s = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.10, throughput_mbps=0.0,
                          alert=True, source='real')
    d = TELEMETRY.diagnose([s])
    assert d.type == 'congestion', f'120ms+10% 丢包应为 congestion，实际 {d.type}'


def test_near_total_loss_is_link_down():
    s = TelemetrySnapshot(latency_ms=999.0, packet_loss=1.0, throughput_mbps=0.0,
                          alert=True, source='real')
    assert TELEMETRY.diagnose([s]).type == 'link_down'


def test_loss_thresholds_are_the_documented_ones():
    assert LOSS_LINK_DOWN == 0.9
    assert LOSS_DEGRADED == 0.05
    assert LOSS_LINK_DOWN > LOSS_DEGRADED


# ---------- 置信度 ----------

def test_confidence_drops_for_simulated_source():
    """同样 120ms，模拟数据得出的结论置信度必须更低。"""
    real = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=0.0,
                             alert=True, source='real')
    fake = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=0.0,
                             alert=True, source='simulated')
    d_real = TELEMETRY.diagnose([real])
    d_fake = TELEMETRY.diagnose([fake])
    assert d_real.type == d_fake.type == 'congestion'
    assert d_fake.confidence < d_real.confidence, \
        f'模拟数据置信度 {d_fake.confidence} 不应 ≥ 真实的 {d_real.confidence}'


def test_simulated_evidence_carries_source():
    s = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=0.0,
                          alert=True, source='simulated')
    d = TELEMETRY.diagnose([s])
    assert d.evidence.get('source') == 'simulated', '结论要能看出是基于哪种数据得出的'


def test_confidence_grows_with_evidence_strength():
    assert _confidence(1.0, 10) > _confidence(0.3, 10)
    assert _confidence(0.8, 10) > _confidence(0.8, 2), '样本少时置信度应更低'
    assert _confidence(0.5, 10, corroborated=True) > _confidence(0.5, 10)


# ---------- 降级路径 ----------

def test_no_probe_target_falls_back_and_says_why(monkeypatch):
    monkeypatch.delenv('NETMIND_PROBE_TARGET', raising=False)
    snap, why = _real_snapshot()
    assert snap is None
    assert 'NETMIND_PROBE_TARGET' in why


def test_unreachable_driver_falls_back_without_raising(monkeypatch):
    monkeypatch.setenv('NETMIND_PROBE_TARGET', '192.0.2.1')
    monkeypatch.setenv('NETMIND_DRIVER', 'simulation')      # 无 _connect
    snap, why = _real_snapshot()
    assert snap is None and why


def test_fallback_snapshot_is_labelled_simulated(monkeypatch):
    monkeypatch.delenv('NETMIND_PROBE_TARGET', raising=False)
    snap = TELEMETRY.sample(record=False)
    assert snap.source == 'simulated', '降级产物必须自报家门'
    prov = TELEMETRY.provenance()
    assert prov['real'] is False and prov['reason']


# ---------- 真探测路径（假 SSH） ----------

class _FakeConn:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def send_command(self, cmd):
        self.sent.append(cmd)
        return self.reply


class _FakeDriver:
    name = 'fake-ssh'
    real = False

    def __init__(self, conn):
        self._connection = conn

    def _connect(self):
        return self._connection


def test_real_probe_uses_ssh_and_parses(monkeypatch):
    reply = ('--- 192.0.2.1 ping statistics ---\n'
             '10 packets transmitted, 9 packets received, 10% packet loss\n'
             'round-trip min/avg/max = 118.2/120.4/122.0 ms')
    conn = _FakeConn(reply)
    monkeypatch.setenv('NETMIND_PROBE_TARGET', '192.0.2.1')
    monkeypatch.setenv('NETMIND_PROBE_COUNT', '10')
    monkeypatch.setattr(tel, 'build_driver', lambda: _FakeDriver(conn), raising=False)
    import app.core.transaction as txn
    monkeypatch.setattr(txn, 'build_driver', lambda: _FakeDriver(conn))

    snap, why = _real_snapshot()
    assert why == '' and snap is not None
    assert snap.source == 'real'
    assert snap.latency_ms == 120.4
    assert snap.packet_loss == 0.1
    assert any('192.0.2.1' in c for c in conn.sent), '探测命令里必须带探测目标'
    assert TELEMETRY.diagnose([snap]).type == 'congestion'


def test_probe_output_without_stats_is_not_accepted(monkeypatch):
    """命令没跑成（只回了提示）时不能当成 100% 丢包——那是编造。"""
    conn = _FakeConn('bash: ping: command not found')
    monkeypatch.setenv('NETMIND_PROBE_TARGET', '192.0.2.1')
    import app.core.transaction as txn
    monkeypatch.setattr(txn, 'build_driver', lambda: _FakeDriver(conn))
    snap, why = _real_snapshot()
    assert snap is None, '没采到报文统计却给出了快照'
    assert why


# ---------- 「一切正常」也得有依据 ----------
#
# 此前这条路径直接 `Diagnosis(type='normal')`，吃到 schema 默认的
# confidence=0.9：样本量 1 与 10 给出同一个数、读数贴阈值与极低给出同一个数、
# 模拟数据与真实数据也给出同一个数。而「一切正常」恰恰是全项目最常出现的
# 诊断结论，也是最容易被当成「系统没问题的证明」的那一条。

def _snap(latency, loss=0.0, source='real'):
    return TelemetrySnapshot(latency_ms=latency, packet_loss=loss,
                             throughput_mbps=50, alert=False, source=source)


def test_normal_without_samples_claims_no_confidence():
    d = TELEMETRY.diagnose([])
    assert d.type == 'normal'
    assert d.confidence == 0.0, f'没有样本却说 {d.confidence} 的把握'
    assert '没有任何' in str(d.evidence)


def test_normal_confidence_rises_with_sample_count():
    one = TELEMETRY.diagnose([_snap(1.0)])
    ten = TELEMETRY.diagnose([_snap(1.0)] * 10)
    assert ten.confidence > one.confidence, (
        f'样本量从 1 到 10 置信度没变（{one.confidence} → {ten.confidence}）'
        '——「依据变多」不体现在结论上')


def test_normal_confidence_drops_when_reading_near_the_threshold():
    clear = TELEMETRY.diagnose([_snap(1.0)] * 10)
    near = TELEMETRY.diagnose([_snap(LATENCY_DEGRADED_MS - 5)] * 10)
    assert clear.type == near.type == 'normal'
    assert near.confidence < clear.confidence, (
        '读数贴着劣化阈值时，说「正常」的把握不应与读数极低时相同')


def test_normal_from_simulated_data_is_discounted():
    real = TELEMETRY.diagnose([_snap(1.0)] * 10)
    sim = TELEMETRY.diagnose([_snap(1.0, source='simulated')] * 10)
    assert sim.type == real.type == 'normal'
    assert sim.confidence < real.confidence, (
        '模拟数据得出的「一切正常」与真实数据一样自信——sim 折扣在正常分支没生效')


def test_normal_carries_its_evidence():
    d = TELEMETRY.diagnose([_snap(3.2, 0.001)] * 4)
    assert d.type == 'normal'
    assert d.evidence.get('latency_ms') == 3.2
    assert d.evidence.get('samples') == 4


# ---------- 缺测不得被编成测量值 ----------
#
# to_snapshot 此前对缺失的 rtt/loss 填 999.0 / 1.0 这两个哨兵值。于是
# 「ping 丢了包所以算不出 RTT」会变成「延迟 999ms、丢包 100%」，
# diagnose() 据此判 link_down —— **把「没测到」变成了「测到断链」**，
# 可能对一台其实正常的设备下发处置。带宽同理：没测就填 0.0 也是编一个数。

def test_missing_rtt_stays_missing_instead_of_a_sentinel():
    from app.diagnose.lab_collector import to_snapshot
    m = {'transmitted': 10, 'received': 2, 'rtt_avg_ms': None, 'loss_ratio': 0.8}
    snap = to_snapshot(m, source='lab')
    assert snap.latency_ms is None, '拿不到 RTT 时又填了哨兵值'
    assert snap.packet_loss == 0.8, '有丢包就该照实记着'


def test_missing_throughput_is_not_zero():
    from app.diagnose.lab_collector import to_snapshot
    snap = to_snapshot({'transmitted': 10, 'received': 10,
                        'rtt_avg_ms': 1.0, 'loss_ratio': 0.0}, source='lab')
    assert snap.throughput_mbps is None, '没做带宽测量却填了 0.0'


def test_partial_loss_does_not_get_diagnosed_as_link_down():
    """丢包到算不出 RTT 时，依据是丢包本身，不是伪造的 999ms。"""
    from app.diagnose.lab_collector import to_snapshot
    snap = to_snapshot({'transmitted': 10, 'received': 2,
                        'rtt_avg_ms': None, 'loss_ratio': 0.8}, source='lab')
    d = TELEMETRY.diagnose([snap])
    assert d.type != 'link_down', '80% 丢包但 RTT 缺失，被当成断链了'
    assert d.evidence.get('latency_ms') is None, '证据里不该出现编造的延迟'


def test_nothing_measured_gives_zero_confidence_normal():
    """两项都缺时不要给「健康」，更不要给高置信度。"""
    from app.diagnose.lab_collector import to_snapshot
    snap = to_snapshot({'transmitted': 0, 'received': 0,
                        'rtt_avg_ms': None, 'loss_ratio': None}, source='lab')
    d = TELEMETRY.diagnose([snap])
    assert d.type == 'normal'
    assert d.confidence == 0.0, f'两项都没测到却给了 {d.confidence} 的把握'
    assert '未测到' in str(d.evidence) or '无法判定' in str(d.evidence)


def test_alert_wording_does_not_claim_an_sla_breach():
    """alert 的真实含义是「跨过内置判据」，项目里没有用户约定的 SLA。"""
    # 路径相对**本文件**而不是 cwd：CI 的 pytest 步骤 working-directory 是
    # backend/，从仓库根跑能过、从 backend/ 跑就失败——那不是可复现的测试。
    import pathlib
    _app = pathlib.Path(__file__).resolve().parent.parent / 'app'
    src = ((_app / 'routers' / 'system.py').read_text(encoding='utf-8')
           + (_app / 'routers' / 'telemetry.py').read_text(encoding='utf-8'))
    # 注释里可以提这句（解释为什么不这么写），但代码字符串里不能出现
    code = '\n'.join(l.split('#')[0] for l in src.splitlines())
    assert 'SLA threshold exceeded' not in code, \
        '仍在用「SLA threshold exceeded」——项目未定义 SLO 目标，不能声称 SLA 被违反'
