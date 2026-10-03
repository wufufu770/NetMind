"""自动处置的两道护栏：动哪块、动几次。

此前主工作流的 HealingAgent 是**永远动不了的**：`workflow.py` 调
`TELEMETRY.heal(diag)` 不传 `iface`，而 `remediation.build()` 缺 `iface`
就抛 `RemediationUnavailable`——每次都走「无需处置」分支。更糟的是那一行
无论 heal() 返回什么都记 `Status.success`，审计里看过去就是「自愈成功了」。
cycle 21 做的真自愈，从主路径根本走不到。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core import heal_guard
from app.schemas import Diagnosis


@pytest.fixture
def clean_guard(monkeypatch):
    """每次都从「没配目标、计数为空」开始。"""
    from app.store import STORE
    for k in (heal_guard.IFACE_ENV, heal_guard.BACKUP_ENV, heal_guard.MAX_ATTEMPTS_ENV):
        monkeypatch.delenv(k, raising=False)
    STORE.heal_attempts.clear()
    yield STORE
    STORE.heal_attempts.clear()


# ---------- 目标：不配就不动，且不编造 ----------

def test_no_configured_interface_disables_auto_remediation(clean_guard):
    """没有接口就不自动处置——不猜。猜错会把命令下到错误的口上。"""
    with pytest.raises(heal_guard.HealingDisabled) as e:
        heal_guard.target_for('congestion')
    assert heal_guard.IFACE_ENV in str(e.value)
    assert '不猜' in str(e.value)


def test_link_down_also_needs_a_backup_route(clean_guard, monkeypatch):
    monkeypatch.setenv(heal_guard.IFACE_ENV, 'eth0')
    with pytest.raises(heal_guard.HealingDisabled) as e:
        heal_guard.target_for('link_down')
    assert heal_guard.BACKUP_ENV in str(e.value)
    monkeypatch.setenv(heal_guard.BACKUP_ENV, '10.9.0.0/24 via 192.0.2.9')
    assert heal_guard.target_for('link_down')['backup'] == '10.9.0.0/24 via 192.0.2.9'


def test_heal_reports_disabled_instead_of_pretending(clean_guard):
    """未配置时，报告要说「未执行」，不能给一条编出来的命令。"""
    from app.core.telemetry import TELEMETRY
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9))
    assert r.success is False
    assert r.improvement.get('target_configured') is False
    assert heal_guard.IFACE_ENV in r.summary
    assert not r.improvement.get('planned_commands')


def test_heal_acts_once_target_is_configured(clean_guard, monkeypatch):
    """配了目标后，同一条调用应真的生成命令。"""
    from app.core.telemetry import TELEMETRY
    monkeypatch.setenv(heal_guard.IFACE_ENV, 'eth0')
    r = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9))
    assert r.improvement.get('planned_commands') == ['tc qdisc del dev eth0 root']


# ---------- 次数：连续失败到顶就停 ----------

class _FakeStore:
    def __init__(self):
        self.heal_attempts = {}
        self.last_heal_execution = ''
        self.dirty = 0
    def mark_dirty(self):
        self.dirty += 1


def test_attempts_accumulate_and_cap(clean_guard, monkeypatch):
    monkeypatch.setenv(heal_guard.MAX_ATTEMPTS_ENV, '3')
    s = _FakeStore()
    for i in range(3):
        assert heal_guard.guard(s, 'congestion', 'eth0') == i
        heal_guard.record_failure(s, 'congestion', 'eth0')
    with pytest.raises(heal_guard.AttemptCapReached) as e:
        heal_guard.guard(s, 'congestion', 'eth0')
    assert '3' in str(e.value) and '人工' in str(e.value)


def test_success_clears_the_counter(clean_guard, monkeypatch):
    """真修好过一次就算解决了，下次是新问题，不该继承旧账。"""
    s = _FakeStore()
    heal_guard.record_failure(s, 'congestion', 'eth0')
    heal_guard.record_failure(s, 'congestion', 'eth0')
    assert heal_guard.check_attempt(s, 'congestion', 'eth0') == 2
    heal_guard.record_success(s, 'congestion', 'eth0')
    assert heal_guard.check_attempt(s, 'congestion', 'eth0') == 0


def test_counter_expires_after_cooldown(clean_guard, monkeypatch):
    """冷却期过后旧账作废——否则一次偶发失败会永久锁死后续处置。"""
    s = _FakeStore()
    heal_guard.record_failure(s, 'congestion', 'eth0', now=1000.0)
    assert heal_guard.check_attempt(s, 'congestion', 'eth0', now=1001.0) == 1
    later = 1000.0 + heal_guard.COOLDOWN_SEC + 1
    assert heal_guard.check_attempt(s, 'congestion', 'eth0', now=later) == 0


def test_different_interfaces_have_separate_budgets(clean_guard):
    """按 (诊断, 接口) 记账：另一个口的故障不该被这边的次数挡住。"""
    s = _FakeStore()
    for _ in range(3):
        heal_guard.record_failure(s, 'congestion', 'eth0')
    assert heal_guard.check_attempt(s, 'congestion', 'eth1') == 0
    with pytest.raises(heal_guard.AttemptCapReached):
        heal_guard.guard(s, 'congestion', 'eth0')


def test_dry_run_does_not_consume_the_budget(clean_guard, monkeypatch):
    """干跑没动过设备，不该消耗重试预算——那不是「试过一次没成」。"""
    from app.core.telemetry import TELEMETRY
    monkeypatch.setenv(heal_guard.IFACE_ENV, 'eth0')
    monkeypatch.setenv('NETMIND_ENABLE_REAL_COMMANDS', 'false')
    monkeypatch.setenv('NETMIND_DRIVER', 'simulation')
    TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    assert clean_guard.heal_attempts == {}, '干跑被当成一次失败尝试记了账'


def test_counter_is_persisted_not_just_in_memory(clean_guard, monkeypatch):
    """计数只在内存里的话，重启一次就把上限绕过去了。"""
    from app.store import STORE
    heal_guard.record_failure(STORE, 'congestion', 'eth0')
    raw = STORE.to_json()
    assert raw.get('heal_attempts'), 'heal_attempts 未进持久化快照——重启即可绕过上限'
    assert raw.get('last_heal_execution') is not None
