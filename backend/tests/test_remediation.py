"""自愈闭环的回归。

此前 `heal()` 的「动作」是字典里的中文描述串（'启用备用路径并重新下发流表'），
不产生任何真实副作用——自愈是场表演。现在动作是真命令，过安全门、真下发、
重测验证，并如实区分「干跑没下发」/「设备拒绝执行」/「下发了没改善」。
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.remediation import (REMEDIATIONS, ROLLBACK_INSPECT, ROLLBACK_INVERSE,
                                  ROLLBACK_NONE, RemediationUnavailable, build,
                                  rollback_info)
from app.core.security import SECURITY
from app.schemas import Diagnosis, TelemetrySnapshot


# ---------- 方案生成 ----------

def test_normal_diagnosis_has_no_action():
    """诊断正常时不编造动作。"""
    with pytest.raises(RemediationUnavailable):
        build(Diagnosis(type='normal', confidence=0.9))


def test_missing_params_refuses_rather_than_invents():
    """没有 iface 就不知道该清哪个队列的整形——编一条出来只会打到错误接口。"""
    with pytest.raises(RemediationUnavailable) as e:
        build(Diagnosis(type='congestion', confidence=0.9))
    assert 'iface' in str(e.value)


# 真实设备模式下，每种可自动处置的诊断各配一份真实参数样本
_SAMPLES = {
    'congestion':      dict(iface='eth0'),
    'link_down':       dict(iface='eth0', backup='10.9.0.0/24 via 192.0.2.9'),
}


@pytest.fixture
def real_device_mode(monkeypatch):
    """切到真实设备模式。

    SecurityChecker._real_mode() 要两个条件同时成立：驱动是 ssh/netconf，
    且 NETMIND_ENABLE_REAL_COMMANDS=true。只设驱动会静默落回 Mininet 校验，
    拿 `eth0` 去比 `shN-ethN` 而误判成非法接口。
    """
    monkeypatch.setenv('NETMIND_DRIVER', 'ssh')
    monkeypatch.setenv('NETMIND_ENABLE_REAL_COMMANDS', 'true')


def test_every_remedy_template_passes_the_security_gate(real_device_mode):
    """生成的每条命令都必须能过白名单——否则方案下发时会被自己拦下。"""
    for kind, kw in _SAMPLES.items():
        plan = build(Diagnosis(type=kind, confidence=0.9), **kw)
        for p in plan.policies:
            for c in p.commands:
                assert SECURITY.check(c).success is True, f'{kind} 的命令过不了安全门: {c}'


def test_every_inverse_rollback_survives_its_own_security_gate(real_device_mode):
    """可回滚的处置，回滚命令必须真能过门。

    这里查的是**回滚实际走的那条路径**：`SECURITY.check(cmd, allow_dangerous=True)`。
    危险操作在这条路径上仍要拿出归属证明（流表认 cookie、路由认登记的规格），
    所以光断言「命令在白名单里」是不够的——那会漏掉「回滚被自己拦下」这种
    只在真正撤销那一刻才暴露的废回滚。
    """
    from app.store import STORE
    for kind, kw in _SAMPLES.items():
        info = rollback_info(kind, {'iface': 'eth0', 'backup': kw.get('backup')})
        if info['capability'] != ROLLBACK_INVERSE:
            continue
        plan = build(Diagnosis(type=kind, confidence=0.9), **kw)
        # 模拟 deploy() 的登记动作——没有归属证明，危险操作的回滚必然被拒
        STORE.register_routes([c for p in plan.policies for c in p.commands], 'test-exec')
        try:
            for p in plan.policies:
                for c in p.rollback_commands:
                    r = SECURITY.check(c, allow_dangerous=True)
                    assert r.success is True, f'{kind} 的回滚过不了安全门: {c} → {r.output}'
        finally:
            STORE.owned_routes.clear()


def test_rollback_without_ownership_is_refused(real_device_mode):
    """反向确认：没登记过的路由不许删。

    这是 `ip route del` 回滚能安全存在的前提——安全门对它的放行条件不是
    「命令在白名单里」，而是「这条路由是本系统加的」。少这一条，
    回滚能力就等于「一个删任意路由的开关」。
    """
    from app.store import STORE
    STORE.owned_routes.clear()
    r = SECURITY.check('ip route del 10.9.0.0/24 via 192.0.2.9 dev eth0', allow_dangerous=True)
    assert r.success is False, '未登记的路由被放行删除'
    assert 'deny' in r.output or 'approval' in r.output


def test_route_registration_covers_exactly_what_was_added(real_device_mode):
    """登记只认 add，且规格按空白归一——排版差异不该当成两条路由。"""
    from app.store import STORE
    STORE.owned_routes.clear()
    try:
        n = STORE.register_routes([
            'ip route add 10.9.0.0/24 via 192.0.2.9 dev eth0',
            'ip route add   10.9.0.0/24   via 192.0.2.9   dev eth0',   # 同一条
            'ip route del 0.0.0.0/0',                                   # del 不登记
        ], 'test-exec')
        assert n == 1, f'只应登记 1 条，实际 {n}'
        assert STORE.has_owned_route('ip route del 10.9.0.0/24 via 192.0.2.9 dev eth0')
        assert not STORE.has_owned_route('ip route del 0.0.0.0/0')
        # 注销后不再有归属证明
        STORE.release_routes(['ip route del 10.9.0.0/24 via 192.0.2.9 dev eth0'])
        assert not STORE.has_owned_route('ip route del 10.9.0.0/24 via 192.0.2.9 dev eth0')
    finally:
        STORE.owned_routes.clear()


def test_congestion_rollback_is_declared_not_reversible():
    """congestion 处置删掉了设备原有整形但没记参数——不能声称可回滚。

    早先把 `tc qdisc show` 塞进 rollback_commands，让「已回滚」在一件都没撤销的
    情况下成立。这里钉住：它只能是 inspect，且回滚命令不得被当成撤销执行。
    """
    info = rollback_info('congestion', {'iface': 'eth0'})
    assert info['capability'] == ROLLBACK_INSPECT
    assert info['executed'] == [], '只读命令不该被当成撤销动作'
    assert info['read_only'] == ['tc qdisc show dev eth0']


def test_rollback_capability_is_not_claimed_without_an_inverse(real_device_mode):
    """三种处置里，能真撤销的必须真给逆命令，不能只给只读检查。"""
    assert rollback_info('link_down', {'iface': 'eth0', 'backup': '10.9.0.0/24'})['capability'] == ROLLBACK_INVERSE
    # 缺参数就没有可撤销的对象
    assert rollback_info('link_down', {'iface': 'eth0'})['capability'] == ROLLBACK_NONE


def test_tc_commands_are_rejected_outside_real_device_mode(monkeypatch):
    """反向确认：仿真模式下 `eth0` 会被 Mininet 接口名校验挡下。

    这条是为了钉住上一条的前提——真实模式的宽松是「两个 env 都设了才放宽」，
    不是安全门整体松了。少设一个 NETMIND_ENABLE_REAL_COMMANDS 就该退回严格校验。
    """
    monkeypatch.setenv('NETMIND_DRIVER', 'ssh')
    monkeypatch.delenv('NETMIND_ENABLE_REAL_COMMANDS', raising=False)
    assert SECURITY.check('tc qdisc del dev eth0 root').success is False


def test_generated_command_matches_template():
    plan = build(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert plan.policies[0].commands == ['tc qdisc del dev eth0 root']


def test_config_error_has_no_auto_remediation():
    """`ovs-ofctl del-flows` 是危险操作，只放行带 NetMind cookie 的流表。

    拿不到归属证明就不该自动动手——绕开它等于把「回滚任意流表」做成一个开关。
    """
    with pytest.raises(RemediationUnavailable):
        build(Diagnosis(type='config_error', confidence=0.9), bridge='br0')


def test_link_down_generates_failover_route():
    """备用路径生成的是 `ip route add` 不是 `replace`。

    安全门白名单（security.py 的 allow_patterns）只认 add|del，
    写 replace 会生成一条自己把自己拦下的命令。
    """
    plan = build(Diagnosis(type='link_down', confidence=0.9), iface='eth0',
                 backup='10.9.0.0/24 via 192.0.2.9')
    cmd = plan.policies[0].commands[0]
    assert cmd.startswith('ip route add ')
    assert '10.9.0.0/24' in cmd
    assert 'dev eth0' in cmd


def test_remediations_table_covers_only_auto_actionable_kinds():
    for k in ('congestion', 'link_down'):
        assert k in REMEDIATIONS
    for k in ('config_error', 'anomaly_traffic'):
        assert k not in REMEDIATIONS, \
            f'{k} 刻意不给自动处置，不该回到自动处置表里'
    for kind, spec in REMEDIATIONS.items():
        assert set(spec) == {'template', 'intent', 'requires'}, \
            f'{kind} 的处置规格字段不齐'
        assert spec['requires'], f'{kind} 没声明需要哪些参数，缺参数时会编出半成品命令'


# ---------- 执行与报告 ----------

@pytest.fixture
def sim_trans(monkeypatch):
    """把 TransactionManager 换成可控的假实现，隔离网络。

    rollback 是真实存在的行为，必须可观测——早先 heal() 里压根没有回滚调用，
    而 docstring 写着「触发回滚」。这里把调用记下来，测试才有东西可断言。
    """
    import app.core.transaction as txn
    from app.schemas import CommandResult, DeployResult

    class _T:
        def __init__(self):
            self.calls = []
            self.rollbacks = []
            self.mode = 'real'
            self.ok = True
            self.rollback_ok = True
            self.rollback_has_commands = True
        def deploy(self, eid, plan):
            self.calls.append((eid, plan))
            return DeployResult(execution_id=eid,
                                executed=[CommandResult(command='x', success=self.ok, output='')],
                                success=self.ok, mode=self.mode)
        def rollback(self, plan, eid, reason='', policies=None):
            self.rollbacks.append((eid, reason))
            has = self.rollback_has_commands and any(p.rollback_commands for p in plan.policies)
            return DeployResult(execution_id=eid, executed=[], rolled_back=has,
                                rollback_complete=self.rollback_ok if has else None,
                                success=self.rollback_ok, mode=self.mode)
    t = _T()
    monkeypatch.setattr(txn, 'TRANSACTION', t)
    monkeypatch.setenv('NETMIND_DRIVER', 'simulation')
    monkeypatch.delenv('NETMIND_PROBE_TARGET', raising=False)
    return t


# ---------- 未改善时的回滚 ----------

def _no_improvement(monkeypatch, sim_trans, kind, **kw):
    """让 heal() 走「真下发 + 指标没改善」这条分支。"""
    from app.core.telemetry import TELEMETRY
    TELEMETRY._last_fallback = ''
    sim_trans.mode = 'real'
    seq = iter([
        TelemetrySnapshot(latency_ms=200.0, packet_loss=0.30, throughput_mbps=10, alert=True, source='real'),
        TelemetrySnapshot(latency_ms=200.0, packet_loss=0.30, throughput_mbps=10, alert=True, source='real'),
    ])
    monkeypatch.setattr(TELEMETRY, 'sample', lambda record=True: next(seq))
    return TELEMETRY.heal(Diagnosis(type=kind, confidence=0.9), **kw)


def test_no_improvement_triggers_an_actual_rollback(monkeypatch, sim_trans):
    """下发成功但没改善时，必须真去撤销——这正是此前完全缺失的一步。

    早先这里只把 success 报成 False，坏变更留在设备上，而 docstring 却写着
    「触发回滚」。报告里不出现 rollback 段就说明回滚没发生。
    """
    r = _no_improvement(monkeypatch, sim_trans, 'link_down',
                        iface='eth0', backup='10.9.0.0/24 via 192.0.2.9')
    assert sim_trans.rollbacks, '未改善却没有触发回滚'
    assert r.success is False
    assert r.improvement['rollback']['attempted'] is True
    assert r.improvement['rollback']['rolled_back'] is True
    assert '未改善' in r.summary and '已回滚' in r.summary


def test_rollback_failure_is_reported_as_incomplete(monkeypatch, sim_trans):
    """回滚命令下发失败要说「回滚未完成」，不能含糊成别的。"""
    sim_trans.rollback_ok = False
    r = _no_improvement(monkeypatch, sim_trans, 'link_down',
                        iface='eth0', backup='10.9.0.0/24 via 192.0.2.9')
    assert r.improvement['rollback']['complete'] is False
    assert '回滚未完成' in r.summary
    assert r.success is False


def test_remediation_without_inverse_says_it_cannot_roll_back(monkeypatch, sim_trans):
    """congestion 撤不回来时必须明说撤不回来。"""
    r = _no_improvement(monkeypatch, sim_trans, 'congestion', iface='eth0')
    rb = r.improvement['rollback']
    assert rb['capability'] == ROLLBACK_INSPECT
    assert rb['rolled_back'] is False
    assert '无法自动回滚' in r.summary
    assert '未记录' in rb['note'], '要说清为什么撤不回来'
    assert r.success is False


def test_rollback_reason_records_the_measurement(monkeypatch, sim_trans):
    """回滚的原因得带上前后测值——否则事后无从判断该不该撤。"""
    _no_improvement(monkeypatch, sim_trans, 'link_down',
                    iface='eth0', backup='10.9.0.0/24 via 192.0.2.9')
    _eid, reason = sim_trans.rollbacks[-1]
    assert '200.0' in reason and 'no improvement' in reason


def test_improvement_does_not_roll_back(monkeypatch, sim_trans):
    """改善了就别多此一举地撤——撤了反而把好状态搞回去。"""
    from app.core.telemetry import TELEMETRY
    TELEMETRY._last_fallback = ''
    sim_trans.mode = 'real'
    seq = iter([
        TelemetrySnapshot(latency_ms=200.0, packet_loss=0.30, throughput_mbps=10, alert=True, source='real'),
        TelemetrySnapshot(latency_ms=0.2, packet_loss=0.0, throughput_mbps=90, alert=False, source='real'),
    ])
    monkeypatch.setattr(TELEMETRY, 'sample', lambda record=True: next(seq))
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert r.success is True
    assert not sim_trans.rollbacks, '改善后不该回滚'
    assert r.improvement['rollback']['attempted'] is False


def test_dry_run_mode_never_reports_success(monkeypatch, sim_trans):
    """干跑模式下即使指标看着好了也不报成功——设备根本没被动过。"""
    from app.core.telemetry import TELEMETRY
    sim_trans.mode = 'simulated'
    TELEMETRY._last_fallback = '未配置 NETMIND_PROBE_TARGET'
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert r.success is False
    assert '未真的下发' in r.summary


def test_applied_flag_tracks_whether_the_device_was_touched(monkeypatch, sim_trans):
    """`applied` 回答的是「设备被动过没有」，不是「命令跑没跑」。

    仿真模式下 deploy 也会 success=True，此时 applied 必须为 False——
    否则调用方会拿它当「已下发」的凭据。
    """
    from app.core.telemetry import TELEMETRY
    TELEMETRY._last_fallback = ''
    sim_trans.mode = 'simulated'
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert r.improvement['deploy_success'] is True
    assert r.improvement['applied'] is False

    sim_trans.mode = 'real'
    r2 = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert r2.improvement['applied'] is True


def test_real_mode_but_device_rejected_is_reported_distinctly(monkeypatch, sim_trans):
    """真模式但设备拒绝执行——这跟「没下发」是两回事，文案不能说混。"""
    from app.core.telemetry import TELEMETRY
    sim_trans.mode = 'real'
    sim_trans.ok = False
    TELEMETRY._last_fallback = ''
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert r.success is False
    assert '设备拒绝执行' in r.summary


def test_no_action_path_reports_no_device_change(monkeypatch, sim_trans):
    from app.core.telemetry import TELEMETRY
    TELEMETRY._last_fallback = '未配置 NETMIND_PROBE_TARGET'
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9))   # 不给 iface
    assert r.success is False
    assert '未产生任何设备侧变更' in r.summary
    assert not sim_trans.calls, '没生成方案就不该下发'


def test_report_records_planned_commands_and_measurement_source(monkeypatch, sim_trans):
    from app.core.telemetry import TELEMETRY
    sim_trans.mode = 'real'
    TELEMETRY._last_fallback = ''
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert r.improvement['planned_commands'] == ['tc qdisc del dev eth0 root']
    assert r.improvement['measured'] in ('real', 'simulated')
    assert 'latency_before_ms' in r.improvement and 'latency_after_ms' in r.improvement


# ---------- anomaly_traffic：诊断与处置方向相反，因此不给自动处置 ----------

def test_anomaly_traffic_has_no_auto_remediation_because_the_action_is_backwards():
    """该诊断唯一的触发条件是「带宽跌幅 ≥50%」，而原处置是**限速**。

    也就是「带宽掉了」→「把带宽再限死一点」。拿实测数据推演
    （tests/fixtures/lab/throughput-real.json）：健康态 21.08Mbps、限速态
    4.01Mbps（跌 81% → 判 anomaly_traffic），处置要限到 5Mbps——限值高于
    已经跌下去的带宽，基本是空动作；链路跌到 8Mbps 时则是把它弄得更糟。

    带宽下降是症状不是病因：拥塞、链路劣化、策略变更、设备故障，没有哪一条
    能靠限速修好。所以它可以**被诊断**，但不该**被自动处置**。
    """
    from app.core import telemetry as tel
    from app.core.remediation import RemediationUnavailable

    assert 'anomaly_traffic' not in REMEDIATIONS, \
        'anomaly_traffic 又有了自动处置——先确认限速还适不适合「带宽下降」这个诊断'
    # 诊断本身保留：它标记了一个真实存在的异常，值得让人看见
    assert tel.THROUGHPUT_DROP_RATIO == 0.5
    with pytest.raises(RemediationUnavailable) as e:
        build(Diagnosis(type='anomaly_traffic', confidence=0.9), iface='eth0')
    assert 'anomaly_traffic' in str(e.value)


def test_no_remediation_template_limits_bandwidth():
    """兜底断言：处置表里不该再出现任何「限速」类模板。

    只要没有「带宽下降 → 限速」这种配对，方向就不会再反。
    真要限速某个流量，那是**策略意图**该做的事（由人写策略），
    不是从一次遥测异常里自动推出来的动作。
    """
    for kind, spec in REMEDIATIONS.items():
        assert 'rate' not in spec['template'], (
            f'{kind} 的处置模板是限速：限速修不好「带宽下降」，'
            f'会把它弄得更糟 —— {spec["template"]}')


def test_refusal_explains_that_it_is_deliberate_not_a_gap():
    """「刻意不做」和「不知道怎么做」要让使用者分得开。

    运维只看到「没有对应的处置原语」，只能自己去翻源码才知道这不是能力缺失。
    措辞里必须带上原因。
    """
    for kind in ('anomaly_traffic', 'config_error'):
        with pytest.raises(RemediationUnavailable) as e:
            build(Diagnosis(type=kind, confidence=0.9), iface='eth0', bridge='br0')
        msg = str(e.value)
        assert '不做自动处置' in msg, f'{kind} 的拒绝理由没说清是刻意选择：{msg[:80]}'
        assert len(msg) > 40, f'{kind} 的拒绝理由太短，运维看不出为什么：{msg}'
