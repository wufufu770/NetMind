from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body
from ..schemas import ToolCallRequest, WorkflowRunRequest

router = APIRouter()

@router.post('/api/tools/call')
def call_tool(req: ToolCallRequest):
    from ..core.tools_registry import TOOLS
    return TOOLS.call(req)

@router.get('/api/tools')
def list_tool_registry():
    from ..core.tools_registry import TOOLS
    return TOOLS.list_tools()

@router.get('/api/langgraph/graph')
def langgraph_graph():
    from ..core.langgraph_adapter import LANGGRAPH_ENGINE as LANGGRAPH_COMPAT
    return LANGGRAPH_COMPAT.describe()

@router.post('/api/langgraph/run')
def langgraph_run(req: WorkflowRunRequest, require_approval: bool=False):
    from ..core.langgraph_adapter import LANGGRAPH_ENGINE as LANGGRAPH_COMPAT
    return LANGGRAPH_COMPAT.run(req.intent_text, dry_run=req.dry_run, require_approval=require_approval)

@router.get('/api/langgraph/interrupts')
def langgraph_interrupts():
    from ..core.langgraph_adapter import LANGGRAPH_ENGINE as LANGGRAPH_COMPAT
    return LANGGRAPH_COMPAT.list_interrupts()

@router.post('/api/langgraph/resume/{interrupt_id}')
def langgraph_resume(interrupt_id: str, decision: str = Body(..., embed=True)):
    from ..core.langgraph_adapter import LANGGRAPH_ENGINE as LANGGRAPH_COMPAT
    out=LANGGRAPH_COMPAT.resume(interrupt_id, decision)
    if not out.get('ok'): raise HTTPException(404, out.get('error'))
    return out

@router.get('/api/mcp/list_tools')
def mcp_list_tools():
    from ..core.mcp_protocol import MCP
    return MCP.list_tools()

@router.post('/api/mcp/call_tool')
def mcp_call_tool(req: ToolCallRequest):
    from ..core.mcp_protocol import MCP
    return MCP.call_tool(req.tool_name, req.arguments, req.dry_run)

@router.post('/api/mcp/servers/{name}/test')
def mcp_test_server(name: str, payload: dict):
    from ..core.mcp_protocol import MCP
    return MCP.test_server(name, payload)
