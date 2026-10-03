from __future__ import annotations
import os
from ..schemas import PolicySet, DeployResult
from .security import SECURITY
from ..drivers.simulation import SimulationDriver
from ..drivers.ssh_driver import SSHDriver
from ..drivers.netconf_driver import NETCONFDriver
from ..store import STORE

def build_driver():
    name=os.getenv('NETMIND_DRIVER','simulation').lower()
    if name == 'ssh': return SSHDriver()
    if name == 'netconf': return NETCONFDriver()
    return SimulationDriver()

class TransactionManager:
    """部署与回滚。

    回滚集的定义是「**已成功下发**的命令」，不是「本次计划过的命令」。原实现把
    整份 rollback_commands 在下发前就累积进去，于是策略 b 的首条命令失败时，
    策略 b（一条都没下发成功）也跟着被回滚——对从未发生的变更动手，在真实设备
    上是有害的。

    两类失败的回滚策略不同：
      · **被安全门拦下** → 确定没下发，不回滚它
      · **driver 报失败** → 设备可能已部分应用，按保守处理把它也纳入回滚
    """

    def __init__(self): self.driver=build_driver()

    def deploy(self, execution_id: str, policy_set: PolicySet) -> DeployResult:
        mode=self.driver.mode()
        planned=[c for p in policy_set.policies for c in (list(p.commands)+list(p.rollback_commands))]
        STORE.register_flow_cookies(planned, execution_id)
        # 登记本系统 add 下去的路由——没有这条登记，回滚时的 `ip route del`
        # 拿不出归属证明，安全门会把每次撤销都当成「删任意路由」而拒绝。
        STORE.register_routes(planned, execution_id)
        executed=[]
        applied=[]        # 已成功下发的 (命令, 所属策略) —— 回滚只看这个

        def _rollback(reason: str) -> tuple[bool, bool | None]:
            """回滚已下发的东西。返回 (是否触发过回滚, 是否全部成功)。

            回滚命令取自**已下发命令所属策略**的 rollback_commands，而不是
            「本次计划过的所有命令」——后者会把没下发成功的策略也回滚掉。
            """
            if not applied:
                return False, None      # 什么都没下发，不该说「已回滚」
            order=[]
            for _cmd, pol in applied:
                if pol is not None and not any(p is pol for p in order):
                    order.append(pol)
            rcmds=[]
            for pol in reversed(order):
                rcmds.extend(pol.rollback_commands)
            ok = True
            for rcmd in rcmds:
                rb = SECURITY.check(rcmd, allow_dangerous=True)
                if not rb.success:
                    ok = False
                    executed.append(rb)
                else:
                    executed.append(self.driver.execute(rcmd))
            STORE.release_flow_cookies(planned)   # 回滚结束，cookie 不再是「已签发」
            STORE.release_routes(planned)
            STORE.log('deploy', reason, 'error', execution_id)
            return True, ok

        for policy in policy_set.policies:
            for cmd in policy.commands:
                sec = SECURITY.check(cmd)
                if not sec.success:
                    executed.append(sec)
                    rolled, complete = _rollback(f'deploy blocked: {sec.output}')
                    return DeployResult(execution_id=execution_id, executed=executed,
                                        rolled_back=rolled, rollback_complete=complete,
                                        success=False, mode=mode)
                res = self.driver.execute(cmd)
                executed.append(res)
                if not res.success:
                    # 设备可能已部分应用，保守地把它所属策略也纳入回滚
                    applied.append((cmd, policy))
                    rolled, complete = _rollback('driver execution failed')
                    return DeployResult(execution_id=execution_id, executed=executed,
                                        rolled_back=rolled, rollback_complete=complete,
                                        success=False, mode=mode)
                applied.append((cmd, policy))

        STORE.log('deploy', f'deployed {len(applied)} commands through {self.driver.name} (mode={mode})', 'info', execution_id)
        return DeployResult(execution_id=execution_id, executed=executed,
                            rolled_back=False, success=True, mode=mode)

    def rollback(self, policy_set: PolicySet, execution_id: str,
                 reason: str = 'manual rollback',
                 policies: list | None = None) -> DeployResult:
        """公开回滚：把已下发策略的逆操作**真跑一遍**。

        此前回滚只是 deploy() 内部的闭包——部署一旦成功返回，就再没有任何入口
        能撤销它。于是「下发成功但把网络搞得更糟」这种最该撤销的场景，反而是
        唯一撤不掉的：调用方只能把 success 报成 False，然后看着坏变更留在设备上。

        `policies` 传「**确实下发过**的策略」。不传就默认整份 policy_set 都
        下发过——那只在调用方能保证时才对；对没下发成功的策略动手，在真实设备
        上是有害的。

        返回的 `rolled_back` 只表示「确实有回滚命令被执行」，`rollback_complete`
        表示「这些命令是否全部成功」。没有回滚命令时前者为 False——
        什么都没回滚就不能说回滚了。
        """
        mode = self.driver.mode()
        applied = policy_set.policies if policies is None else policies
        # 逆序回滚：后加的先撤
        rcmds = [c for pol in reversed(list(applied)) for c in pol.rollback_commands]
        executed = []
        ok = True
        for rcmd in rcmds:
            rb = SECURITY.check(rcmd, allow_dangerous=True)
            if not rb.success:
                ok = False
                executed.append(rb)
                continue
            res = self.driver.execute(rcmd)
            executed.append(res)
            if not res.success:
                ok = False
        STORE.release_flow_cookies(
            [c for p in applied for c in (list(p.commands) + list(p.rollback_commands))])
        STORE.release_routes(
            [c for p in applied for c in (list(p.commands) + list(p.rollback_commands))])
        STORE.log('rollback', f'{reason}: {len(rcmds)} command(s), complete={ok}',
                  'error' if not ok else 'info', execution_id)
        return DeployResult(execution_id=execution_id, executed=executed,
                            rolled_back=bool(rcmds), rollback_complete=ok if rcmds else None,
                            success=ok, mode=mode)

    def rollback_plan(self, policy_set: PolicySet) -> list[str]:
        out=[]
        for p in policy_set.policies:
            out.extend(p.rollback_commands)
        return list(reversed(out))

TRANSACTION=TransactionManager()
