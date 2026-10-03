"""闭环「不演戏」的回归测试。

这些用例的判据不是「处置成功」，而是：
  · 没重测就不许报成功（verified=False → success 必须 False）
  · 重测没改善就报失败，且要触发回滚
  · 重测本身失败时如实记录异常，不拿处置前的值冒充处置后的值

core/telemetry.py 的 heal() 此前 success 恒为 True（字段默认值且从无人赋值），
「处置成功」是写死的，与是否真做了事无关。这里逐条锁住相反的行为。
"""
from app.core.telemetry import TELEMETRY
from app.diagnose.closed_loop import compare, improved, run_closed_loop
from app.schemas import Diagnosis, HealingReport, TelemetrySnapshot


def _snap(lat, loss, source='lab'):
    return TelemetrySnapshot(latency_ms=lat, packet_loss=loss, throughput_mbps=0.0,
                             alert=lat > 50 or loss > 0.05, source=source)


class _M:
    def __init__(self, seq):
        self.seq = list(seq)
        self.n = 0

    def __call__(self):
        v = self.seq[min(self.n, len(self.seq) - 1)]
        self.n += 1
        if isinstance(v, Exception):
            raise v
        return v


def _m(seq, state='healthy', loss=0.0, rtt=1.0):
    return {'transmitted': 10, 'received': 10, 'loss_ratio': loss,
            'rtt_min_ms': rtt, 'rtt_avg_ms': rtt, 'rtt_max_ms': rtt,
            'per_packet_ms': [rtt] * 10, 'seq_seen': list(range(10)),
            'has_rtt': True, 'state': state}


# ---------- 对比判据 ----------

def test_compare_reports_measured_delta_not_conclusion():
    c = compare(_snap(120.0, 0.1), _snap(0.12, 0.0))
    assert c['latency_before_ms'] == 120.0 and c['latency_after_ms'] == 0.12
    assert c['loss_before'] == 0.1 and c['loss_after'] == 0.0
    assert c['latency_ratio'] is not None


def test_improved_requires_both_latency_and_loss():
    assert improved(compare(_snap(120.0, 0.1), _snap(1.0, 0.0))) is True
    assert improved(compare(_snap(120.0, 0.0), _snap(120.0, 0.0))) is False
    # 延迟降了但没降够
    assert improved(compare(_snap(100.0, 0.0), _snap(90.0, 0.0))) is False


# ---------- 正例 ----------

def test_real_recovery_is_reported_as_success():
    m = _M([_m(None, 'congested', loss=0.1, rtt=120.0), _m(None, 'healthy', rtt=0.12)])
    r = run_closed_loop(measure=m, act=lambda d: '清除 qdisc',
                        diagnosis=Diagnosis(type='congestion', confidence=0.9))
    assert r.verified is True
    assert r.success is True
    assert r.before_snapshot.latency_ms == 120.0
    assert r.after_snapshot.latency_ms == 0.12


# ---------- 反例：这是重点 ----------

def test_no_improvement_is_reported_as_failure_and_rolls_back():
    """处置没效果时必须报失败并回滚——绝不能沿用旧的「恒 success=True」。"""
    m = _M([_m(None, 'congested', loss=0.1, rtt=120.0), _m(None, 'congested', loss=0.12, rtt=120.0)])
    r = run_closed_loop(measure=m, act=lambda d: '空操作',
                        rollback=lambda: '已回滚',
                        diagnosis=Diagnosis(type='congestion', confidence=0.9))
    assert r.verified is True, '重测做了就是 verified'
    assert r.success is False, '没改善却报成功 = 在演戏'
    assert '已回滚' in r.action_taken
    assert r.improvement['rollback'] == '已回滚'
    assert '未改善' in r.summary


def test_probe_failure_is_recorded_not_faked():
    """重测探针挂了：不得拿处置前的值当处置后的值充数。"""
    m = _M([_m(None, 'congested', loss=0.1, rtt=120.0), RuntimeError('probe timeout')])
    r = run_closed_loop(measure=m, act=lambda d: '清除 qdisc',
                        diagnosis=Diagnosis(type='congestion', confidence=0.9))
    assert r.verified is False
    assert r.success is False
    assert 'error' in r.improvement and 'probe timeout' in r.improvement['error']
    assert '未验证' in r.summary


def test_unverified_never_reports_success():
    """verified=False 时 success 必须为 False，无论其他字段长什么样。"""
    r = HealingReport(action_taken='x', before_snapshot=_snap(1, 0), after_snapshot=_snap(1, 0),
                      success=True, verified=False, summary='s')
    assert r.success is True, 'schema 允许显式传入矛盾组合'
    # 闭环自己产出的报告不会出现这种组合
    m = _M([_m(None, 'healthy'), RuntimeError('down')])
    got = run_closed_loop(measure=m, act=lambda d: 'a')
    assert got.verified is False and got.success is False


# ---------- 模拟路径的 heal() 也不再假成功 ----------

def test_simulated_heal_admits_it_did_not_verify():
    """没配处置目标时，自愈不得编造动作。

    此前 heal() 的「动作」是字典里的中文描述串，不产生任何真实副作用。
    现在缺处置目标（NETMIND_HEAL_IFACE 等）就如实说未启用、缺什么，
    并且 success=False。措辞从「需要参数」改成「未配置」是刻意的：
    缺的不是某次调用的参数，而是系统级的前置条件——说成前者会让人
    以为补个调用参数就能自愈。
    """
    TELEMETRY.fault = 'congestion'
    d = TELEMETRY.diagnose([_snap(68, 0.018, 'simulated')])
    r = TELEMETRY.heal(d)
    assert r.success is False, '没真正处置不得报成功'
    assert '未产生任何设备侧变更' in r.summary
    assert '未配置' in r.summary or '未启用' in r.summary
    assert r.improvement.get('target_configured') is False


def test_normal_diagnosis_is_not_reported_as_failure():
    """系统本来就健康时，「前后没变化」是无事可做，不是处置失败。

    但也不能报 success——没有东西被治好。summary 必须把这点说清楚，
    否则读者会把「无需处置」误读成「处置失败」。
    """
    m = _M([_m(None, 'healthy', loss=0.0, rtt=0.12), _m(None, 'healthy', loss=0.0, rtt=0.11)])
    rolled = []
    r = run_closed_loop(measure=m, act=lambda d: '无需动作', rollback=lambda: rolled.append(1) or 'x',
                        diagnosis=Diagnosis(type='normal'))
    assert r.verified is True
    assert r.success is False, '没有东西被治好，不得报成功'
    assert r.improvement.get('no_action_needed') is True
    assert '无需处置' in r.summary and '不是失败' in r.summary
    assert not rolled, '无需处置时不该触发回滚'
