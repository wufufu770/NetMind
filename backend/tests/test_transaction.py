"""事务与回滚语义的回归。

这个模块零直接覆盖，而项目的核心主张就是「可回滚」——宣称最响的地方恰好是
测试最空的地方。本文件把回滚语义钉死：

  · 正常部署：全部命令按序执行，不触发回滚
  · 安全门拦下：已执行的命令必须回滚，且只回滚**已执行**的
  · driver 执行失败：同上
  · 回滚自身被拦：如实反映 rollback_complete=False，不粉饰
  · 首条命令就被拦：什么都没执行，不该说「已回滚」

以及两条被修掉的真问题：
  · 回滚集曾包含「尚未下发」的策略的回滚命令——回滚不存在的变更可能有害
  · cookie 登记后就再也不清，失败回滚后仍可用于后续回滚
"""
import pytest

from app.core import transaction as tx_mod
from app.core.security import SECURITY
from app.core.transaction import TransactionManager
from app.drivers.simulation import SimulationDriver
from app.schemas import CommandResult, Policy, PolicySet
from app.store import STORE


def _ck(n: int) -> str:
    """NetMind 格式的流表 cookie。回滚命令必须带它才被放行——这是设计，不是巧合。"""
    return f'0x4e65744d{n:08x}'


def _p(pid, cmds, rb_cmds, n=None):
    """n 给定时给每条命令配一个独立 cookie（贴近 PolicyGenerator 的真实产出）。"""
    def with_ck(cmd, i):
        return cmd if n is None else f'{cmd} cookie={_ck(n * 10 + i)}'
    return Policy(id=pid, type='acl', name=pid, action='permit',
                  commands=[with_ck(c, i) for i, c in enumerate(cmds)],
                  rollback_commands=[with_ck(c, 100 + i) for i, c in enumerate(rb_cmds)])


def _ps(*policies):
    return PolicySet(intent_id='int-test', policies=list(policies))


@pytest.fixture
def mgr(monkeypatch):
    """一个可控的 TransactionManager，driver 可替换。"""
    m = TransactionManager()
    m.driver = SimulationDriver()
    return m


# ---------- 正常路径 ----------

def test_deploy_runs_all_commands_in_order(mgr):
    ps = _ps(_p('a', ['ovs-ofctl add-flow s1'], []),
             _p('b', ['ovs-ofctl add-flow s2'], []))
    r = mgr.deploy('e1', ps)
    assert r.success is True
    assert r.rolled_back is False
    assert r.rollback_complete is None, '未触发回滚时 rollback_complete 应为 None'
    assert mgr.driver.commands == ['ovs-ofctl add-flow s1', 'ovs-ofctl add-flow s2']


def test_deploy_registers_cookies_so_rollback_is_allowed(mgr):
    cmd = 'ovs-ofctl del-flows s1 cookie=0x4e65744dcafe0011'
    ps = _ps(_p('a', [cmd], []))
    mgr.deploy('e-cookie', ps)
    assert SECURITY.check(cmd, allow_dangerous=True).success is True


def test_rollback_plan_is_reverse_of_declaration_order(mgr):
    ps = _ps(_p('a', ['c1', 'c2'], ['r1', 'r2']),
             _p('b', ['c3'], ['r3']))
    assert mgr.rollback_plan(ps) == ['r3', 'r2', 'r1']


# ---------- 安全门拦下 ----------

def test_blocked_command_triggers_rollback_of_already_executed(mgr):
    """第二条被安全门拦下 → 第一条已执行 → 必须回滚第一条。"""
    ps = _ps(_p('a', ['ovs-ofctl add-flow s1'], []),
             _p('b', ['rm -rf /'], []))
    r = mgr.deploy('e-block', ps)
    assert r.success is False
    assert r.rolled_back is True
    assert 'ovs-ofctl add-flow s1' in mgr.driver.commands, '已执行的首条命令没被回滚'


def test_first_command_blocked_means_nothing_ran(mgr):
    """首条就被拦：什么都没执行，不该报告「已回滚」。"""
    ps = _ps(_p('a', ['rm -rf /'], []))
    r = mgr.deploy('e-first-block', ps)
    assert r.success is False
    assert mgr.driver.commands == [], '被拦的命令不应真的下发'
    assert r.rolled_back is False, '没有任何执行发生，不该说「已回滚」'
    assert r.rollback_complete is None


# ---------- driver 执行失败 ----------

class _FlakyDriver(SimulationDriver):
    """第 N 条命令开始失败，用来模拟「下发到一半设备拒绝」。"""
    name = 'flaky'
    real = False

    def __init__(self, fail_at):
        super().__init__()
        self.fail_at = fail_at

    def execute(self, command):
        self.commands.append(command)
        if len(self.commands) >= self.fail_at:
            return CommandResult(command=command, success=False, output='device rejected')
        return CommandResult(command=command, success=True, output='ok')


def test_driver_failure_rolls_back_prior_commands(mgr):
    mgr.driver = _FlakyDriver(fail_at=2)
    ps = _ps(_p('a', ['ovs-ofctl add-flow s1', 'ovs-ofctl add-flow s2'],
                ['ovs-ofctl del-flows s1'], n=7))
    r = mgr.deploy('e-drv', ps)
    assert r.success is False
    assert r.rolled_back is True
    assert any('del-flows s1' in c for c in mgr.driver.commands), '失败的命令没有被回滚'


def test_rollback_complete_false_when_rollback_itself_blocked(mgr):
    """回滚计划里混入不带 cookie 的危险命令 → 该条被拦，且必须如实报
    rollback_complete=False。

    这是真实会发生的：手写策略、或 LLM 生成了一条错误的回滚命令（`rm -rf /`）。
    带上 cookie 的危险命令会被 register_flow_cookies 登记后放行（那是 NetMind
    自己签发的，合法）；**不带 cookie** 的才说明它不是 NetMind 计划过的流表，
    必须拦。
    """
    mgr.driver = _FlakyDriver(fail_at=2)
    ps = _ps(_p('a', ['ovs-ofctl add-flow s1', 'ovs-ofctl add-flow s2'],  # 第 2 条失败
                ['rm -rf /', 'ovs-ofctl del-flows s1'], n=9))
    r = mgr.deploy('e-rb-block', ps)
    assert r.success is False
    assert r.rolled_back is True
    assert r.rollback_complete is False, '回滚被拦却报 rollback_complete=True'
    assert not any('rm -rf' in c for c in mgr.driver.commands), \
        '不带 cookie 的危险回滚命令被真的下发了'
    assert any('del-flows s1' in c for c in mgr.driver.commands), \
        '合法的那条回滚命令应该照常执行——不能因为一条被拦就全不做'


# ---------- 已修掉的两个真问题 ----------

def test_rollback_does_not_include_never_applied_policy(mgr):
    """回滚集只能包含**已下发**的策略的回滚命令。

    原实现先把本策略的 rollback_commands 累积进去再执行它的 commands，于是
    第二条命令失败时，第一条策略回滚了，第二条策略（没下发成功）也跟着回滚——
    回滚一个从未发生的变更，在真实设备上是有害的。
    """
    # 用「被安全门拦下」触发未下发分支——那是确定没发生的变更。
    # driver 报错时按保守处理回滚（设备可能已部分应用），那是另一条语义。
    ps = _ps(_p('a', ['ovs-ofctl add-flow s1'], ['ovs-ofctl del-flows s1'], n=1),
             _p('b', ['rm -rf /'], ['ovs-ofctl del-flows s2'], n=2))
    r = mgr.deploy('e-scope', ps)
    assert r.success is False
    assert any('del-flows s1' in c for c in mgr.driver.commands), '已下发的策略应回滚'
    assert not any('del-flows s2' in c for c in mgr.driver.commands), \
        '未成功下发的策略不应被回滚——那是对从未发生的变更动手'


def test_cookies_are_released_after_failed_rollback(mgr):
    """失败的回滚不该把 cookie 永久留在登记表里。"""
    mgr.driver = _FlakyDriver(fail_at=2)
    cmd = 'ovs-ofctl del-flows s1 cookie=0x4e65744dcafe0033'
    ps = _ps(_p('a', ['ovs-ofctl add-flow s1', cmd], [cmd]))
    r = mgr.deploy('e-cookie-clean', ps)
    assert r.rolled_back is True, '本用例需要真的触发回滚'
    # 回滚已完成（无论成功与否），这个 cookie 不该再可用于后续回滚
    assert SECURITY.check(cmd, allow_dangerous=True).success is False, \
        '回滚结束后 cookie 仍可用——后续可拿它做特权回滚'


# ---------- driver 装配 ----------

def test_build_driver_follows_env(monkeypatch):
    monkeypatch.setenv('NETMIND_DRIVER', 'simulation')
    assert tx_mod.build_driver().name == 'simulation'
    monkeypatch.setenv('NETMIND_DRIVER', 'ssh')
    assert tx_mod.build_driver().name == 'ssh'
    monkeypatch.setenv('NETMIND_DRIVER', 'netconf')
    assert tx_mod.build_driver().name == 'netconf'
    monkeypatch.setenv('NETMIND_DRIVER', 'weird-value')
    assert tx_mod.build_driver().name == 'simulation', '未知驱动名应回落到 simulation'
