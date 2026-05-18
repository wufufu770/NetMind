from __future__ import annotations
from typing import Any, Dict
from .langgraph_compat import LANGGRAPH_COMPAT

class LangGraphAutoAdapter:
    """Runtime adapter for LangGraph.

    If langgraph is installed, the adapter builds a minimal StateGraph wrapper so
    the project uses the LangChain/LangGraph ecosystem. If the optional runtime is
    unavailable or incompatible, it falls back to the built-in compatible engine.
    """
    def __init__(self):
        self._compat = LANGGRAPH_COMPAT
        self._engine_name = 'LangGraphCompatEngine'
        self._state_graph_available = False
        self._error = None
        try:
            from langgraph.graph import StateGraph, END  # type: ignore
            self._StateGraph = StateGraph
            self._END = END
            self._state_graph_available = True
            self._engine_name = 'langgraph.StateGraph'
        except Exception as exc:  # pragma: no cover - depends on optional package
            self._StateGraph = None
            self._END = None
            self._error = str(exc)

    def describe(self) -> Dict[str, Any]:
        base = self._compat.describe()
        base.update({
            'engine': self._engine_name,
            'real_langgraph_available': self._state_graph_available,
            'fallback_engine': 'LangGraphCompatEngine',
            'import_error': self._error,
        })
        return base

    def run(self, intent_text: str, dry_run: bool = False, require_approval: bool = False) -> Dict[str, Any]:
        if not self._state_graph_available:
            out = self._compat.run(intent_text, dry_run=dry_run, require_approval=require_approval)
            out['graph_state']['engine'] = 'LangGraphCompatEngine'
            return out
        try:
            # Keep the project deterministic: the actual domain execution remains in
            # ORCHESTRATOR, while StateGraph owns the lifecycle envelope.
            def execute(state: Dict[str, Any]) -> Dict[str, Any]:
                result = self._compat.run(
                    state['intent_text'],
                    dry_run=state.get('dry_run', False),
                    require_approval=state.get('require_approval', False),
                )
                return {**state, 'result': result}

            graph = self._StateGraph(dict)
            graph.add_node('execute_closed_loop', execute)
            graph.set_entry_point('execute_closed_loop')
            graph.add_edge('execute_closed_loop', self._END)
            compiled = graph.compile()
            final_state = compiled.invoke({'intent_text': intent_text, 'dry_run': dry_run, 'require_approval': require_approval})
            out = final_state['result']
            out['graph_state']['engine'] = 'langgraph.StateGraph'
            return out
        except Exception as exc:  # pragma: no cover - defensive fallback
            out = self._compat.run(intent_text, dry_run=dry_run, require_approval=require_approval)
            out['graph_state']['engine'] = 'LangGraphCompatEngine'
            out['graph_state']['langgraph_error'] = str(exc)
            return out

    def list_interrupts(self):
        return self._compat.list_interrupts()

    def resume(self, interrupt_id: str, decision: str):
        return self._compat.resume(interrupt_id, decision)

LANGGRAPH_ENGINE = LangGraphAutoAdapter()
