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

from app.core.remediation import REMEDIATIONS, RemediationUnavailable, build
from app.core.security import SECURITY
from app.schemas import Diagnosis


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
    'anomaly_traffic': dict(iface='eth0', rate_mbps=5),
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


def test_every_rollback_command_passes_the_security_gate(real_device_mode):
    """回滚命令同样要能过门。回滚走的是同一条安全检查路径，
    过不了门的回滚在真正需要撤销的那一刻才会被发现是废的。"""
    for kind, kw in _SAMPLES.items():
        plan = build(Diagnosis(type=kind, confidence=0.9), **kw)
        for p in plan.policies:
            for c in p.rollback_commands:
                assert SECURITY.check(c).success is True, f'{kind} 的回滚过不了安全门: {c}'


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
    for k in ('congestion', 'link_down', 'anomaly_traffic'):
        assert k in REMEDIATIONS
    assert 'config_error' not in REMEDIATIONS, \
        'config_error 的流表回滚需归属证明，不该进自动处置表'
    for kind, spec in REMEDIATIONS.items():
        assert set(spec) == {'template', 'intent', 'requires'}, \
            f'{kind} 的处置规格字段不齐'
        assert spec['requires'], f'{kind} 没声明需要哪些参数，缺参数时会编出半成品命令'


# ---------- 执行与报告 ----------

@pytest.fixture
def sim_trans(monkeypatch):
    """把 TransactionManager 换成可控的假实现，隔离网络。"""
    import app.core.transaction as txn
    from app.schemas import CommandResult, DeployResult

    class _T:
        def __init__(self):
            self.calls = []
            self.mode = 'real'
            self.ok = True
        def deploy(self, eid, plan):
            self.calls.append((eid, plan))
            return DeployResult(execution_id=eid,
                                executed=[CommandResult(command='x', success=self.ok, output='')],
                                success=self.ok, mode=self.mode)
    t = _T()
    monkeypatch.setattr(txn, 'TRANSACTION', t)
    monkeypatch.setenv('NETMIND_DRIVER', 'simulation')
    monkeypatch.delenv('NETMIND_PROBE_TARGET', raising=False)
    return t


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
