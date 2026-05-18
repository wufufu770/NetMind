from __future__ import annotations
import time
from ..schemas import *
from ..store import STORE
from .rule_engine import RULE_ENGINE
from .verification import VERIFIER
from .transaction import TRANSACTION
from .telemetry import TELEMETRY
from .model_adapter import MODEL_ADAPTER
from .tools_registry import TOOLS

class WorkflowOrchestrator:
    def parse_intent_with_agent(self, text: str) -> tuple[IntentDSL, dict]:
        intent, meta = MODEL_ADAPTER.parse_intent(text, 'IntentAgent')
        if intent is not None:
            STORE.log('agent', f"IntentAgent parsed DSL with model {meta['model_id']}", 'info', data={'model_id':meta['model_id'], 'fallback':False})
            return intent, meta
        fallback_intent = RULE_ENGINE.parse_intent(text)
        STORE.log('agent', f"IntentAgent model parse failed; fallback to RuleEngine: {meta.get('error','unknown')}", 'warn', data={'model_id':meta.get('model_id'), 'fallback':True})
        return fallback_intent, meta

    def build_tool_context(self, intent: IntentDSL) -> dict:
        calls=[]
        def call(name, arguments):
            res=TOOLS.call(ToolCallRequest(tool_name=name, arguments=arguments, dry_run=True))
            calls.append({'tool':name,'arguments':arguments,'result':res})
            return res.get('result') if isinstance(res, dict) else res
        return {
            'calls': calls,
            'topology': call('topology_tool', {}),
            'telemetry': call('telemetry_tool', {}),
            'path': call('free_path_finder', {'src':intent.target.src,'dst':intent.target.dst}),
            'sla': call('free_sla_estimator', {'latency_ms':intent.sla.latency_ms}),
            'bandwidth': call('free_bandwidth_estimator', {'traffic_type':intent.target.traffic_type}),
        }

    def plan_with_agent(self, intent: IntentDSL) -> tuple[PolicySet, dict]:
        tool_context=self.build_tool_context(intent)
        ps, meta = MODEL_ADAPTER.plan_policy(intent, 'PlannerAgent', tool_context=tool_context)
        meta['tool_context']=tool_context
        if ps is not None and ps.policies:
            STORE.log('planner', f"PlannerAgent generated {len(ps.policies)} policies with model {meta['model_id']}", 'info', data={'model_id':meta['model_id'], 'fallback':False})
            return ps, meta
        fallback_ps = RULE_ENGINE.plan(intent)
        STORE.log('planner', f"PlannerAgent model plan failed; fallback to RuleEngine: {meta.get('error','unknown')}", 'warn', data={'model_id':meta.get('model_id'), 'fallback':True})
        return fallback_ps, meta

    def run_closed_loop(self, text: str, dry_run: bool=False, workflow_id: str='default') -> Execution:
        workflow=STORE.workflows.get(workflow_id) or STORE.workflows.get('default')
        ex=Execution(intent_text=text, status=Status.running)
        STORE.executions[ex.execution_id]=ex
        STORE.log('intent', f'user submitted intent: {text}', 'info', ex.execution_id, data={'workflow_id': workflow.id if workflow else workflow_id})
        ex.steps.append(AgentStep(agent='OrchestratorAgent', status=Status.success, input={'text':text,'workflow_id':workflow_id}, output={'workflow_id':workflow.id if workflow else 'default','workflow_name':workflow.name if workflow else '默认闭环工作流','nodes':(workflow.graph.get('nodes') if workflow else [])}, tools=[{'name':'free_workflow_selector'}], duration_ms=30))

        t=time.time(); intent,intent_meta=self.parse_intent_with_agent(text); ex.intent=intent
        intent_tools=[{'name':'model_adapter_chat','model_id':intent_meta.get('model_id'), 'fallback': bool(intent_meta.get('fallback'))}]
        if intent_meta.get('fallback'):
            intent_tools.append({'name':'rule_engine_parse','reason':intent_meta.get('error','model failed')})
        ex.steps.append(AgentStep(agent='IntentAgent', status=Status.warning if intent_meta.get('fallback') else Status.success, input={'text':text}, output={**intent.model_dump(), '_meta':intent_meta}, tools=intent_tools, duration_ms=int((time.time()-t)*1000)+50))
        STORE.log('agent','IntentAgent parsed DSL successfully','info',ex.execution_id, data={'model_id':intent_meta.get('model_id'), 'fallback':bool(intent_meta.get('fallback'))})

        t=time.time(); ps,plan_meta=self.plan_with_agent(intent); ex.policy_set=ps
        plan_tools=[{'name':'model_adapter_chat','model_id':plan_meta.get('model_id'), 'fallback': bool(plan_meta.get('fallback'))}]
        for c in plan_meta.get('tool_context',{}).get('calls',[]):
            plan_tools.append({'name':c.get('tool'), 'free_builtin': True, 'ok': c.get('result',{}).get('ok') if isinstance(c.get('result'), dict) else True})
        if plan_meta.get('fallback'):
            plan_tools.append({'name':'rule_engine_match','reason':plan_meta.get('error','model failed')})
        ex.steps.append(AgentStep(agent='PlannerAgent', status=Status.warning if plan_meta.get('fallback') else Status.success, input=intent.model_dump(), output={**ps.model_dump(), '_meta':plan_meta}, tools=plan_tools, duration_ms=int((time.time()-t)*1000)+80))
        STORE.log('planner', f'generated {len(ps.policies)} policies', 'info', ex.execution_id, data={'model_id':plan_meta.get('model_id'), 'fallback':bool(plan_meta.get('fallback')), 'source':ps.source})

        t=time.time(); vr=VERIFIER.check(ps, intent); ex.verification=vr
        ex.steps.append(AgentStep(agent='VerifierAgent', status=Status.warning if vr.conflicts else Status.success, input=ps.model_dump(), output=vr.model_dump(), tools=[{'name':'policy_verifier'},{'name':'security_check'}], duration_ms=int((time.time()-t)*1000)+70))
        if vr.conflicts: STORE.log('verify', f'{len(vr.conflicts)} verification issues found', 'warn', ex.execution_id)
        if not dry_run and vr.passed:
            t=time.time(); dep=TRANSACTION.deploy(ex.execution_id, vr.fixed_policy_set or ps); ex.deploy=dep
            ex.steps.append(AgentStep(agent='DeployAgent', status=Status.success if dep.success else Status.failed, input=ps.model_dump(), output=dep.model_dump(), tools=[{'name':'transaction_manager'}], duration_ms=int((time.time()-t)*1000)+120))
        elif dry_run:
            ex.steps.append(AgentStep(agent='DeployAgent', status=Status.waiting, output={'dry_run':True}))
        else:
            ex.steps.append(AgentStep(agent='DeployAgent', status=Status.approval if vr.need_human else Status.failed, output={'reason':'verification not passed'}))
        if workflow and workflow.id == 'telemetry_only':
            ex.steps.append(AgentStep(agent='DeployAgent', status=Status.waiting, output={'skipped_by_workflow':True,'workflow_id':workflow.id}))
        snap=TELEMETRY.sample(); ex.telemetry.append(snap); ex.steps.append(AgentStep(agent='TelemetryAgent', status=Status.success, output=snap.model_dump(), tools=[{'name':'telemetry_tool'},{'name':'free_latency_probe','free_builtin':True}], duration_ms=20))
        diag=TELEMETRY.diagnose([snap]); ex.diagnosis=diag; ex.steps.append(AgentStep(agent='DiagnosisAgent', status=Status.success, output=diag.model_dump(), duration_ms=22))
        if diag.type != 'normal':
            h=TELEMETRY.heal(diag); ex.healing=h; ex.steps.append(AgentStep(agent='HealingAgent', status=Status.success, output=h.model_dump(), duration_ms=95))
        else:
            ex.steps.append(AgentStep(agent='HealingAgent', status=Status.waiting, output={'reason':'no alert'}))
        ex.status=Status.success if not ex.verification or ex.verification.passed else Status.warning
        return ex

ORCHESTRATOR=WorkflowOrchestrator()
