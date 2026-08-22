from __future__ import annotations
from fastapi import APIRouter, Body
from ..schemas import ChatRequest
from ..store import STORE
from ..core.model_adapter import MODEL_ADAPTER
from .common import get_execution

router = APIRouter()

@router.get('/api/agents')
def agents(): return list(STORE.agents.values())

@router.get('/api/agents/executions/{execution_id}')
def agent_execution(execution_id: str): return get_execution(execution_id).steps

@router.post('/api/agents/negotiate')
def negotiate(payload: dict):
    return {'rounds':[{'domain':'campus','proposal':'raise meeting priority'},{'domain':'guest','counter':'keep 5Mbps limit'},{'domain':'orchestrator','final':'meeting priority + guest isolation'}], 'agreed':True}

@router.post('/api/agents/chat')
def chat(question: str = Body(..., embed=True), model_id: str = Body('mock', embed=True)):
    return MODEL_ADAPTER.chat(model_id,[{'role':'user','content':question}])

@router.post('/api/chat/ask')
def chat_ask(req: ChatRequest):
    from ..core.chat_agent import CHAT_AGENT
    return CHAT_AGENT.answer(req.question)
