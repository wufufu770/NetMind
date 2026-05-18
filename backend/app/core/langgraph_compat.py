
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional
from ..schemas import AgentStep, Status, Execution, IntentRequest
from ..store import STORE
from .workflow import ORCHESTRATOR

@dataclass
class GraphNode:
    name: str
    role: str
    status: str = 'waiting'
    interrupt: bool = False

@dataclass
class GraphEdge:
    source: str
    target: str
    condition: str = 'always'

@dataclass
class InterruptRecord:
    interrupt_id: str
    execution_id: str
    node: str
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    decision: Optional[str] = None

class LangGraphCompatEngine:
    """A small StateGraph-compatible runtime used when langgraph is not installed.

    It keeps the same product semantics required by the spec: named nodes,
    conditional edges, human interrupt points, resume, and serializable graph state.
    Swapping it with real LangGraph only requires replacing this class at the API boundary.
    """
    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {
            'OrchestratorAgent': GraphNode('OrchestratorAgent','primary'),
            'IntentAgent': GraphNode('IntentAgent','secondary'),
            'PlannerAgent': GraphNode('PlannerAgent','secondary'),
            'VerifierAgent': GraphNode('VerifierAgent','secondary'),
            'HumanApproval': GraphNode('HumanApproval','approval', interrupt=True),
            'DeployAgent': GraphNode('DeployAgent','secondary'),
            'TelemetryAgent': GraphNode('TelemetryAgent','tertiary'),
            'DiagnosisAgent': GraphNode('DiagnosisAgent','tertiary'),
            'HealingAgent': GraphNode('HealingAgent','tertiary'),
        }
        self.edges: List[GraphEdge] = [
            GraphEdge('OrchestratorAgent','IntentAgent'),
            GraphEdge('IntentAgent','PlannerAgent'),
            GraphEdge('PlannerAgent','VerifierAgent'),
            GraphEdge('VerifierAgent','HumanApproval','verification.need_human == true'),
            GraphEdge('VerifierAgent','DeployAgent','verification.passed == true'),
            GraphEdge('HumanApproval','DeployAgent','approval.approved == true'),
            GraphEdge('DeployAgent','TelemetryAgent'),
            GraphEdge('TelemetryAgent','DiagnosisAgent'),
            GraphEdge('DiagnosisAgent','HealingAgent','diagnosis.type != normal'),
        ]
        self.interrupts: Dict[str, InterruptRecord] = {}

    def describe(self) -> Dict[str, Any]:
        return {
            'engine': 'LangGraphCompatEngine',
            'swappable_with': 'langgraph.StateGraph',
            'nodes': [vars(n) for n in self.nodes.values()],
            'edges': [vars(e) for e in self.edges],
            'supports': ['conditional_edges','human_interrupt','resume','serializable_state'],
        }

    def run(self, intent_text: str, dry_run: bool = False, require_approval: bool = False) -> Dict[str, Any]:
        ex = ORCHESTRATOR.run_closed_loop(intent_text, dry_run=dry_run or require_approval)
        graph_state = {'execution_id': ex.execution_id, 'nodes': [], 'edges': [vars(e) for e in self.edges]}
        completed = {s.agent: s.status.value if hasattr(s.status, 'value') else str(s.status) for s in ex.steps}
        for node in self.nodes.values():
            state = completed.get(node.name, 'waiting')
            if node.name == 'HumanApproval' and require_approval:
                state = 'interrupted'
                iid = f'int-{ex.execution_id}'
                self.interrupts[iid] = InterruptRecord(
                    interrupt_id=iid, execution_id=ex.execution_id, node=node.name,
                    reason='策略下发前需要人工确认', payload={'execution_id': ex.execution_id}
                )
                ex.status = Status.approval
            graph_state['nodes'].append({'name': node.name, 'role': node.role, 'status': state, 'interrupt': node.interrupt})
        STORE.executions[ex.execution_id] = ex
        STORE.log('workflow', 'langgraph-compatible workflow executed', 'info', ex.execution_id, graph_state)
        return {'execution': ex.model_dump(mode='json'), 'graph_state': graph_state, 'interrupts': [vars(i) for i in self.interrupts.values() if i.execution_id == ex.execution_id]}

    def list_interrupts(self) -> List[Dict[str, Any]]:
        return [vars(i) for i in self.interrupts.values()]

    def resume(self, interrupt_id: str, decision: str) -> Dict[str, Any]:
        if interrupt_id not in self.interrupts:
            return {'ok': False, 'error': 'interrupt not found'}
        rec = self.interrupts[interrupt_id]
        rec.resolved = True
        rec.decision = decision
        ex = STORE.executions.get(rec.execution_id)
        if ex:
            ex.status = Status.running if decision == 'approved' else Status.failed
            ex.steps.append(AgentStep(agent='HumanApproval', status=Status.success if decision == 'approved' else Status.failed, output={'decision': decision}, duration_ms=1))
            STORE.log('workflow', f'human interrupt resumed: {decision}', 'info', ex.execution_id)
        return {'ok': True, 'interrupt': vars(rec), 'execution': ex.model_dump(mode='json') if ex else None}

LANGGRAPH_COMPAT = LangGraphCompatEngine()
