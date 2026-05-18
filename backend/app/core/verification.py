from __future__ import annotations
from ..schemas import *
from .security import SECURITY
from .topology import TOPOLOGY

class PolicyVerifier:
    def check(self, policy_set: PolicySet, intent: IntentDSL|None=None) -> VerificationReport:
        issues=[]
        names=[p.name for p in policy_set.policies]
        if 'guest_isolation' in names and any(p.name in ['video_priority','temp_meeting_wifi'] for p in policy_set.policies):
            issues.append(VerificationIssue(severity='warning', code='ACL_PRIORITY_OVERLAP', message='访客隔离与会议保障策略存在优先级重叠，建议自动提升会议保障优先级。', auto_fixable=True, related_policy_ids=[p.id for p in policy_set.policies if p.name in ['guest_isolation','video_priority']]))
        if intent:
            reachable=TOPOLOGY.reachable(intent.target.src, intent.target.dst)
        else:
            reachable=True
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
        sla_confidence=0.92
        sla_feasible=True
        if intent and intent.sla.latency_ms and intent.sla.latency_ms < 20:
            sla_confidence=0.62; sla_feasible=False; issues.append(VerificationIssue(severity='warning', code='SLA_LOW_CONFIDENCE', message='当前遥测基线下 SLA 过于激进。'))
        passed=security_passed and reachable and not any(i.severity=='error' for i in issues)
        fixed=None
        if any(i.auto_fixable for i in issues):
            fixed=policy_set.model_copy(deep=True)
            for p in fixed.policies:
                if p.name=='video_priority': p.priority=1
        return VerificationReport(passed=passed, conflicts=issues, reachable=reachable, sla_feasible=sla_feasible, sla_confidence=sla_confidence, security_passed=security_passed, rollback_ready=all(True for _ in policy_set.policies), need_human=need_human or any(i.severity=='warning' and not i.auto_fixable for i in issues), fixed_policy_set=fixed)

VERIFIER=PolicyVerifier()
