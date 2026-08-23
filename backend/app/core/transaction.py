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
    def __init__(self): self.driver=build_driver()
    def deploy(self, execution_id: str, policy_set: PolicySet) -> DeployResult:
        mode=self.driver.mode()
        # 登记本策略集签发的全部流表 cookie：此后回滚路径只放行这些 cookie，
        # 计划外的伪造回滚命令会被门禁拦截。登记含回滚命令本身（与正向命令同源规划）。
        planned=[c for p in policy_set.policies for c in (list(p.commands)+list(p.rollback_commands))]
        STORE.register_flow_cookies(planned, execution_id)
        executed=[]; rollback=[]; rb_all_ok=True
        for policy in policy_set.policies:
            rollback.extend(policy.rollback_commands)
            for cmd in policy.commands:
                sec=SECURITY.check(cmd)
                if not sec.success:
                    executed.append(sec)
                    for rcmd in reversed(rollback):
                        rb=SECURITY.check(rcmd, allow_dangerous=True)
                        rb_all_ok &= bool(rb.success)
                        executed.append(rb if not rb.success else self.driver.execute(rcmd))
                    STORE.log('deploy', f'deploy failed and rolled back: {sec.output}', 'error', execution_id)
                    return DeployResult(execution_id=execution_id, executed=executed, rolled_back=True, rollback_complete=rb_all_ok, success=False, mode=mode)
                res=self.driver.execute(cmd)
                executed.append(res)
                if not res.success:
                    for rcmd in reversed(rollback):
                        rb=SECURITY.check(rcmd, allow_dangerous=True)
                        rb_all_ok &= bool(rb.success)
                        executed.append(rb if not rb.success else self.driver.execute(rcmd))
                    STORE.log('deploy', 'driver execution failed, rollback attempted', 'error', execution_id)
                    return DeployResult(execution_id=execution_id, executed=executed, rolled_back=True, rollback_complete=rb_all_ok, success=False, mode=mode)
        STORE.log('deploy', f'deployed {len(executed)} commands through {self.driver.name} (mode={mode})', 'info', execution_id)
        return DeployResult(execution_id=execution_id, executed=executed, rolled_back=False, success=True, mode=mode)
    def rollback_plan(self, policy_set: PolicySet) -> list[str]:
        out=[]
        for p in policy_set.policies:
            out.extend(p.rollback_commands)
        return list(reversed(out))

TRANSACTION=TransactionManager()
