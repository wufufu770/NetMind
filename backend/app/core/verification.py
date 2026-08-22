from __future__ import annotations
from ..schemas import *
from .security import SECURITY
from .topology import TOPOLOGY

class PolicyVerifier:
    def check(self, policy_set: PolicySet, intent: IntentDSL|None=None) -> VerificationReport:
        issues=[]
        reachable=True
        if intent:
            reachable=TOPOLOGY.reachable(intent.target.src, intent.target.dst)
            if not reachable:
                issues.append(VerificationIssue(severity='error', code='PATH_UNREACHABLE', message=f"{intent.target.src} 到 {intent.target.dst} 在当前拓扑中不可达。", related_policy_ids=[]))
        security_passed=True
        need_human=False
        for p in policy_set.policies:
            for cmd in p.commands:
                res=SECURITY.check(cmd)
                if res.blocked:
                    security_passed=False
                    issues.append(VerificationIssue(severity='error', code='SECURITY_BLOCKED', message=f'{cmd}: {res.output}', related_policy_ids=[p.id]))
                if res.requires_approval:
                    need_human=True
                    issues.append(VerificationIssue(severity='warning', code='NEED_APPROVAL', message=f'{cmd}: 需要人工确认', related_policy_ids=[p.id]))
        sla_feasible=True
        sla_confidence=None
        if intent and intent.sla.latency_ms:
            pl=TOPOLOGY.path_latency(intent.target.src, intent.target.dst)
            target=intent.sla.latency_ms
            if pl is None or pl<=0 or target<=0:
                sla_confidence=0.0; sla_feasible=False
            else:
                sla_confidence=round(max(0.0,min(1.0,0.5+(target-pl)/(2*target))),2)
                sla_feasible=pl<=target
            if not sla_feasible:
                issues.append(VerificationIssue(severity='warning', code='SLA_LOW_CONFIDENCE', message=f'当前拓扑路径最短时延 {pl}ms，无法满足目标 {target}ms。'))
        passed=security_passed and reachable and not any(i.severity=='error' for i in issues)
        fixed=None
        if any(i.auto_fixable for i in issues):
            fixed=policy_set.model_copy(deep=True)
            for p in fixed.policies:
                if p.type=='qos' and 'guarantee' in (p.action or ''):
                    p.priority=1
        rollback_ready=bool(policy_set.policies) and all(p.rollback_commands for p in policy_set.policies)
        return VerificationReport(passed=passed, conflicts=issues, reachable=reachable, sla_feasible=sla_feasible, sla_confidence=sla_confidence, security_passed=security_passed, rollback_ready=rollback_ready, need_human=need_human or any(i.severity=='warning' and not i.auto_fixable for i in issues), fixed_policy_set=fixed)

VERIFIER=PolicyVerifier()
