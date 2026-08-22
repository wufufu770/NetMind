from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..schemas import Approval
from ..store import STORE
from .common import get_execution

router = APIRouter()

@router.post('/api/approvals', response_model=Approval)
def create_approval(approval: Approval): STORE.approvals[approval.approval_id]=approval; return approval

@router.get('/api/approvals')
def list_approvals(): return list(STORE.approvals.values())

@router.post('/api/approvals/{approval_id}/{action}')
def action_approval(approval_id: str, action: str):
    if approval_id not in STORE.approvals: raise HTTPException(404,'approval not found')
    if action not in ['approved','rejected']: raise HTTPException(400,'invalid action')
    STORE.approvals[approval_id].status=action; return STORE.approvals[approval_id]

@router.post('/api/approvals/from-execution/{execution_id}', response_model=Approval)
def approval_from_execution(execution_id: str):
    ex=get_execution(execution_id)
    if not ex.policy_set: raise HTTPException(400,'no policy set')
    appr=Approval(title='确认策略下发', description=f'执行 {execution_id} 包含需要确认的策略/命令。', payload={'execution_id':execution_id, 'policy_set':ex.policy_set.model_dump(mode='json')})
    STORE.approvals[appr.approval_id]=appr
    STORE.log('approval', f'approval created: {appr.approval_id}', 'warn', execution_id)
    return appr

@router.post('/api/approvals/{approval_id}/execute')
def execute_approved(approval_id: str):
    if approval_id not in STORE.approvals: raise HTTPException(404,'approval not found')
    appr=STORE.approvals[approval_id]
    if appr.status!='approved': raise HTTPException(409,'approval is not approved')
    execution_id=appr.payload.get('execution_id')
    if not execution_id: raise HTTPException(400,'approval has no execution')
    from .deploy import deploy
    return deploy(execution_id)

@router.post('/api/approval-requests/from-execution/{execution_id}', response_model=Approval)
def approval_request_from_execution(execution_id: str):
    return approval_from_execution(execution_id)

@router.post('/api/approval-requests/{approval_id}/execute')
def execute_approval_request(approval_id: str):
    return execute_approved(approval_id)
