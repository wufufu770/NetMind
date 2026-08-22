from __future__ import annotations
from fastapi import HTTPException
from ..store import STORE


def get_execution(execution_id: str):
    if execution_id not in STORE.executions: raise HTTPException(404,'execution not found')
    return STORE.executions[execution_id]
