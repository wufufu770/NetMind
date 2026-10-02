"""用真实采集的数据做回归。

tests/fixtures/lab/ 下的报文与带宽数字都是真的——从 docker 里跑的
frrouting/frr 拓扑上抓的 ICMP 回包与 /sys/class/net 的计数器差分，
不是手写的样例。抓取方式见 scripts/lab.sh。

这些测试存在的原因：core/telemetry.py 的判断阈值是在模拟器上拟的，
而模拟器返回硬编码常量，永远不会遇到「有丢包但统计不出 RTT」这类边界。
只有真实数据会暴露。
"""
import json
from pathlib import Path

from app.core.telemetry import TELEMETRY
from app.diagnose.lab_collector import classify, load_fixture, parse_ping, to_snapshot
from app.schemas import TelemetrySnapshot

FIX = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'lab'
THROUGHPUT = json.loads((FIX / 'throughput-real.json').read_text(encoding='utf-8'))


# ---------- 解析真实报文 ----------

def test_parses_real_healthy_capture():
    m = load_fixture('healthy')
    assert m['transmitted'] == 10
    assert m['received'] == 10
    assert m['loss_ratio'] == 0.0
    assert m['rtt_avg_ms'] is not None and m['rtt_avg_ms'] < 5
    assert len(m['per_packet_ms']) == 10
    assert m['state'] == 'healthy'


def test_parses_real_congestion_capture():
    m = load_fixture('congestion')
    assert m['rtt_avg_ms'] > 100, '真实注入 120ms 延迟，回包 RTT 应明显抬高'
    assert m['state'] == 'congested'


def test_real_link_down_has_no_rtt_line_at_all():
    """全断时 ping 根本不打印 round-trip 行——模拟器永远不会遇到这个形态。"""
    m = load_fixture('link_down')
    assert m['received'] == 0
    assert m['has_rtt'] is False
    assert m['rtt_avg_ms'] is None, '缺 RTT 必须是 None，不能填 0——0 会被读成零延迟健康链路'
    assert m['state'] == 'link_down'


def test_loss_computed_from_counters_not_declared():
    """丢包由报文计数推出，不采信声明的百分比。"""
    m = parse_ping('10 packets transmitted, 9 packets received, 0% packet loss')
    assert m['loss_ratio'] == 0.1, '声明 0% 但 1/10 丢失，以计数为准'


def test_classify_handles_unmeasured():
    assert classify({'transmitted': 0, 'loss_ratio': None, 'rtt_avg_ms': None}) == 'unmeasured'


# ---------- 真实数据暴露的既有缺陷 ----------

def test_high_latency_with_healthy_throughput_must_still_be_congested():
    """真实观测：注入 120ms 延迟但不限速时，带宽 18.66Mbps，与健康态 21.08 接近。

    也就是说「延迟升高」与「带宽受限」在真实网络里是**两件独立的事**。
    而 core/telemetry.py 的拥塞规则把两者绑在一起：

        if last.latency_ms > 50 and last.throughput_mbps < 60

    60 是绝对 Mbps 阈值。实验台恰好跑在 ~20Mbps，所以这条规则在本实验台上
    碰巧成立；换到 10Gbps 链路，同样的 120ms 延迟会让 throughput >> 60，
    于是判成 normal——高延迟被漏掉。本测试锁住正确行为：只看延迟也能判拥塞。
    """
    real = THROUGHPUT['states']['delay_only']
    assert real['rtt_avg_ms'] > 100
    assert real['throughput_mbps'] > 0

    # 真实测量喂进既有诊断路径
    snap = TelemetrySnapshot(latency_ms=real['rtt_avg_ms'], packet_loss=real['loss_ratio'],
                             throughput_mbps=real['throughput_mbps'], alert=True)
    diag = TELEMETRY.diagnose([snap])
    assert diag.type == 'congestion', (
        f'高延迟({real["rtt_avg_ms"]}ms) + 正常带宽({real["throughput_mbps"]}Mbps) '
        f'应判为拥塞，实际判成 {diag.type}'
    )


def test_confidence_must_be_derived_from_evidence_not_constant():
    """CONTRIBUTING 规则 2：置信度须由可观测状态推导，不得是编造的常量。

    既有实现对三种状态分别硬编码 .98 / .92 / .88，与证据无关：
    同样是 120ms 延迟，带宽 18Mbps 与带宽 4Mbps 的置信度完全相同。
    """
    hi = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=18.66, alert=True)
    lo = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=4.01, alert=True)
    # 必须给带宽基线，否则绝对 Mbps 本身不携带信息（不知道 4Mbps 对这条链路
    # 是高是低）。有了基线才能看出 4.01 是基线 21.08 的 19%——证据强度不同。
    baseline = THROUGHPUT['states']['healthy']['throughput_mbps']
    d_hi = TELEMETRY.diagnose([hi], baseline_throughput_mbps=baseline)
    d_lo = TELEMETRY.diagnose([lo], baseline_throughput_mbps=baseline)
    assert d_hi.type == d_lo.type == 'congestion'
    assert d_hi.confidence != d_lo.confidence, (
        f'同等延迟下带宽差 4.6 倍，置信度不应相同（实测 {d_hi.confidence} vs {d_lo.confidence}）'
    )


def test_confidence_depends_on_measurement_strength():
    """回包越少、观测越弱，置信度应越低。"""
    strong = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=18.66, alert=True)
    weak = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.45, throughput_mbps=18.66, alert=True)
    d_strong = TELEMETRY.diagnose([strong])
    d_weak = TELEMETRY.diagnose([weak])
    assert d_strong.confidence > d_weak.confidence


def test_no_evidence_yields_no_diagnosis():
    """拿不到测量值时不该给结论。"""
    assert TELEMETRY.diagnose([]).type == 'normal'
    assert TELEMETRY.diagnose(None).type == 'normal'


# ---------- 快照映射 ----------

def test_snapshot_from_real_measurement_marks_source():
    m = load_fixture('link_down')
    snap = to_snapshot(m)
    assert snap.source == 'lab'
    assert snap.alert is True


def test_healthy_real_measurement_is_not_alerted():
    snap = to_snapshot(load_fixture('healthy'))
    assert snap.alert is False


def test_zero_loss_is_not_treated_as_missing():
    """0.0 在 Python 里是 falsy——用 `or` 兜底会把「零丢包」变成「缺测」。

    真实健康态抓包的 loss_ratio 恰为 0.0，这是最容易被 `or` 吞掉的取值。
    to_snapshot 用 `is not None` 判定缺测，锁住正确行为。
    """
    m = load_fixture('healthy')
    assert m['loss_ratio'] == 0.0
    snap = to_snapshot(m)
    assert snap.packet_loss == 0.0, '零丢包不得被兜底成 1.0'
    assert snap.alert is False
