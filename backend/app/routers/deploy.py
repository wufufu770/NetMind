from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..store import STORE
from .common import get_execution

router = APIRouter()

def _transaction():
    from ..core.transaction import TRANSACTION
    return TRANSACTION

def _execute_rollback(execution_id: str) -> dict:
    ex=get_execution(execution_id)
    if ex.deploy is None:
        raise HTTPException(409, 'execution has no deployment to roll back; deploy first')
    txn=_transaction()
    commands=txn.rollback_plan(ex.policy_set)
    if not commands:
        STORE.log('deploy', f'rollback skipped for {execution_id}: empty rollback plan', 'warn', execution_id)
        return {'execution_id': execution_id, 'rolled_back': False, 'rollback_complete': False, 'commands': [], 'executed': [], 'success': False}
    # 回滚命令与正向命令同源规划：执行前把该策略集的 cookie 登记为已签发，
    # 使合法回滚通过所有权校验（部署时已登记过，此处幂等兜底）。
    from ..store import STORE as _STORE
    _STORE.register_flow_cookies(commands, execution_id)
    executed=[]
    for rcmd in commands:
        sec=txn_security_check(rcmd)
        if not sec.success:
            executed.append(sec.model_dump(mode='json'))
            continue
        executed.append(txn.driver.execute(rcmd).model_dump(mode='json'))
    ok=bool(executed) and all(e['success'] for e in executed)
    STORE.log('deploy', f'rollback {"executed" if ok else "incomplete"} for {execution_id}', 'info' if ok else 'error', execution_id, data={'commands': commands})
    return {'execution_id': execution_id, 'rolled_back': ok, 'rollback_complete': ok, 'commands': commands, 'executed': executed, 'success': ok}

def txn_security_check(command: str):
    from ..core.security import SECURITY
    return SECURITY.check(command, allow_dangerous=True)

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
    if ex.deploy is None:
        raise HTTPException(409,'execution has no deployment to roll back; deploy first')
    if not ex.policy_set: raise HTTPException(400,'no policy set')
    return _execute_rollback(execution_id)
