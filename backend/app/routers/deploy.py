from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..store import STORE
from .common import get_execution

router = APIRouter()

def _transaction():
    from ..core.transaction import TRANSACTION
    return TRANSACTION

@router.post('/api/deploy/{execution_id}')
def deploy(execution_id: str):
    ex=get_execution(execution_id)
    if not ex.policy_set: raise HTTPException(400,'no policy set')
    dep=_transaction().deploy(execution_id, ex.policy_set); ex.deploy=dep; return dep

@router.get('/api/deploy/{execution_id}/rollback-plan')
def rollback_plan(execution_id: str):
    ex=get_execution(execution_id)
    if not ex.policy_set: raise HTTPException(400,'no policy set')
    return {'execution_id':execution_id,'rollback_commands':_transaction().rollback_plan(ex.policy_set)}

@router.post('/api/deploy/{execution_id}/rollback')
def rollback_execution(execution_id: str):
    ex=get_execution(execution_id)
    if not ex.policy_set: raise HTTPException(400,'no policy set')
    commands = _transaction().rollback_plan(ex.policy_set)
    STORE.log('deploy', f'rollback plan executed for {execution_id}', 'warn', execution_id, data={'commands': commands})
    return {'execution_id': execution_id, 'rolled_back': True, 'commands': commands, 'success': True}
