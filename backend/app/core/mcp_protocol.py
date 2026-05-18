
from __future__ import annotations
from typing import Dict, Any, List
from ..schemas import ToolCallRequest
from ..store import STORE
from .tools_registry import TOOLS

class MCPProtocol:
    """Local MCP-compatible adapter.

    Implements the two core protocol operations required by the product plan:
    list_tools() and call_tool(). External stdio/SSE/HTTP servers are represented
    in STORE.mcp_servers and can be tested without enabling dangerous execution.
    """
    def list_tools(self) -> Dict[str, Any]:
        tools=[]
        for t in TOOLS.list_tools():
            tools.append({
                'name': t.name,
                'description': t.description,
                'inputSchema': t.parameters_schema or {'type':'object','properties':{}},
                'enabled': t.enabled,
            })
        return {'protocol': 'mcp-compatible-local', 'tools': tools, 'servers': STORE.mcp_servers}

    def call_tool(self, name: str, arguments: Dict[str, Any]|None=None, dry_run: bool=True) -> Dict[str, Any]:
        if name not in STORE.tools:
            return {'ok': False, 'error': 'tool not registered', 'tool': name}
        if not STORE.tools[name].enabled:
            return {'ok': False, 'error': 'tool disabled', 'tool': name}
        result = TOOLS.call(ToolCallRequest(tool_name=name, arguments=arguments or {}, dry_run=dry_run))
        return {'protocol': 'mcp-compatible-local', 'tool': name, 'result': result}

    def test_server(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        STORE.mcp_servers[name] = payload
        transport = payload.get('transport','local')
        return {'ok': True, 'name': name, 'transport': transport, 'capabilities': ['list_tools','call_tool'], 'dry_run': True}

MCP = MCPProtocol()
