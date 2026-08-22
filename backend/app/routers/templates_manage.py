from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..schemas import IntentRequest, ToolCallRequest
from ..store import STORE
from ..core.rule_engine import RULE_ENGINE
from ..core.tools_registry import TOOLS

router = APIRouter()

@router.get('/api/templates/manage/list')
def template_manage_list():
    return [{'template_id': k, 'text': v, 'storage': 'persistent_store.templates', 'business': RULE_ENGINE.infer_business(v)} for k, v in STORE.templates.items()]

@router.post('/api/templates/manage/suggest')
def template_manage_suggest(req: IntentRequest):
    res = TOOLS.call(ToolCallRequest(tool_name='free_template_recommender', arguments={'text': req.text}, dry_run=True))
    return res['result']

@router.post('/api/templates/manage')
def template_manage_create(payload: dict):
    tid = payload.get('template_id') or payload.get('id') or f"tpl-{len(STORE.templates)+1:03d}"
    text = payload.get('text') or payload.get('content') or ''
    if not text.strip(): raise HTTPException(400, 'template text is required')
    STORE.templates[tid] = text
    STORE.log('config', f'template saved: {tid}', 'info', data={'storage':'persistent_store.templates'})
    return {'ok': True, 'template_id': tid, 'text': text, 'storage': 'persistent_store.templates'}

@router.put('/api/templates/manage/{template_id}')
def template_manage_update(template_id: str, payload: dict):
    if template_id not in STORE.templates: raise HTTPException(404, 'template not found')
    STORE.templates[template_id] = payload.get('text', STORE.templates[template_id])
    return {'ok': True, 'template_id': template_id, 'text': STORE.templates[template_id], 'storage': 'persistent_store.templates'}

@router.delete('/api/templates/manage/{template_id}')
def template_manage_delete(template_id: str):
    existed = template_id in STORE.templates
    STORE.templates.pop(template_id, None)
    STORE.log('config', f'template deleted: {template_id}', 'info')
    return {'ok': True, 'deleted': template_id, 'existed': existed}

@router.get('/api/template-manager/list')
def template_manager_list():
    return template_manage_list()

@router.post('/api/template-manager/suggest')
def template_manager_suggest(req: IntentRequest):
    return template_manage_suggest(req)

@router.post('/api/template-manager/create')
def template_manager_create(payload: dict):
    return template_manage_create(payload)

@router.put('/api/template-manager/{template_id}')
def template_manager_update(template_id: str, payload: dict):
    return template_manage_update(template_id, payload)

@router.delete('/api/template-manager/{template_id}')
def template_manager_delete(template_id: str):
    return template_manage_delete(template_id)
