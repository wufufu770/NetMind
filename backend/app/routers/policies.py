from __future__ import annotations
import os
from fastapi import APIRouter
from ..schemas import IntentDSL, PolicySet, VerificationReport
from ..core.workflow import ORCHESTRATOR
from ..core.verification import VERIFIER
from ..store import STORE

router = APIRouter()

@router.post('/api/planner/plan', response_model=PolicySet)
def plan(intent: IntentDSL):
    ps, meta = ORCHESTRATOR.plan_with_agent(intent)
    return ps

@router.post('/api/verification/check', response_model=VerificationReport)
def verify(policy_set: PolicySet, intent: IntentDSL|None=None): return VERIFIER.check(policy_set, intent)

@router.get('/api/security/check')
def security_check(command: str):
    from ..core.security import SECURITY
    return SECURITY.check(command)

@router.get('/api/policy/conflict-matrix')
def policy_conflict_matrix():
    return {
        'acl': [
            {'pair':['allow','deny'], 'risk':'shadowing/priority-overlap', 'auto_fix':'raise business-critical allow priority'},
            {'pair':['guest_isolation','temporary_meeting'], 'risk':'guest access may bypass isolation', 'auto_fix':'scope temporary rule to meeting_server only'},
        ],
        'qos': [
            {'pair':['guarantee_bandwidth','limit_bandwidth'], 'risk':'same traffic class may be over-constrained', 'auto_fix':'split queues by src/dst'},
        ],
        'route': [
            {'pair':['prefer_path','blocked_link'], 'risk':'preferred path may be unavailable', 'auto_fix':'fallback to backup_path'},
        ],
        'security': [
            {'pair':['dangerous_legal','unattended'], 'risk':'requires explicit human approval', 'auto_fix':'create approval node'}
        ]
    }

@router.post('/api/policy/{execution_id}/auto-fix', response_model=VerificationReport)
def auto_fix_policy(execution_id: str):
    from fastapi import HTTPException
    from .common import get_execution
    ex=get_execution(execution_id)
    if not ex.policy_set: raise HTTPException(400,'no policy set')
    report=VERIFIER.check(ex.policy_set, ex.intent)
    if report.fixed_policy_set:
        ex.policy_set=report.fixed_policy_set
        ex.verification=VERIFIER.check(ex.policy_set, ex.intent)
        STORE.log('verify','auto-fixed policy conflicts','info',execution_id)
        return ex.verification
    ex.verification=report
    return report

@router.get('/api/drivers')
def drivers():
    from ..core.transaction import TRANSACTION
    return {'active': TRANSACTION.driver.snapshot(), 'available':['simulation','mininet','ssh','netconf'], 'real_commands_enabled': os.getenv('NETMIND_ENABLE_REAL_COMMANDS','false')}
