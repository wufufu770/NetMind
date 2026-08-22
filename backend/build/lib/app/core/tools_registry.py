from __future__ import annotations
from ..store import STORE
from ..schemas import ToolCallRequest, IntentDSL, Policy, PolicySet
from .security import SECURITY
from .topology import TOPOLOGY
from .telemetry import TELEMETRY
from .rule_engine import RULE_ENGINE
from .verification import VERIFIER

class ToolRegistry:
    """Built-in tool registry used by Agent workflows.

    These tools do not require external API keys. They provide deterministic
    context for tests, demos and LLM prompts before real MCP/network tools are
    connected.
    """
    def list_tools(self):
        return list(STORE.tools.values())

    def call(self, req: ToolCallRequest):
        name=req.tool_name
        args=req.arguments or {}
        try:
            if name == 'topology_tool':
                return {'ok': True, 'result': TOPOLOGY.snapshot()}
            if name == 'telemetry_tool':
                return {'ok': True, 'result': TELEMETRY.sample(record=False).model_dump(mode='json')}
            if name == 'security_check':
                cmd=args.get('command','')
                return {'ok': True, 'result': SECURITY.check(cmd).model_dump(mode='json')}
            if name == 'rule_engine_match':
                text=args.get('text','')
                intent=RULE_ENGINE.parse_intent(text)
                return {'ok': True, 'intent': intent.model_dump(mode='json'), 'matches': RULE_ENGINE.match(intent)}
            if name == 'free_latency_probe':
                src=args.get('src','teacher_terminal'); dst=args.get('dst','meeting_server')
                snap=TELEMETRY.sample(record=False)
                pl=TOPOLOGY.path_latency(src,dst)
                return {'ok': True, 'result': {'src':src,'dst':dst,'latency_ms':snap.latency_ms,'packet_loss':snap.packet_loss,'path_latency_ms':pl,'builtin':True}}
            if name == 'free_bandwidth_estimator':
                traffic=args.get('traffic_type','video')
                base={'video':20,'voip':5,'bulk':50,'data':10}.get(traffic,12)
                return {'ok': True, 'result': {'traffic_type':traffic,'recommended_mbps':base,'confidence':0.86}}
            if name == 'free_path_finder':
                src=args.get('src','teacher_terminal'); dst=args.get('dst','meeting_server')
                path=TOPOLOGY.path(src,dst) or []
                return {'ok': True, 'result': {'src':src,'dst':dst,'reachable':bool(path),'path':path,'nodes':len(TOPOLOGY.snapshot()['nodes'])}}
            if name == 'free_sla_estimator':
                src=args.get('src','teacher_terminal'); dst=args.get('dst','meeting_server')
                target=float(args.get('latency_ms',50) or 50)
                pl=TOPOLOGY.path_latency(src,dst)
                if pl is None or pl<=0 or target<=0:
                    feasible=False; confidence=0.0
                else:
                    feasible=pl<=target
                    confidence=round(max(0.0,min(1.0,0.5+(target-pl)/(2*target))),2)
                return {'ok': True, 'result': {'target_latency_ms':target,'path_latency_ms':pl,'feasible':feasible,'confidence':confidence}}
            if name == 'free_acl_conflict_scan':
                policies=args.get('policies',[])
                parsed=[Policy(**{k:v for k,v in p.items() if k in ('type','name','action','priority','params')}) for p in policies if isinstance(p,dict)]
                issues=VERIFIER._semantic_conflicts(PolicySet(intent_id='scan',policies=parsed))
                return {'ok': True, 'result': {'conflicts':[{'code':i.code,'auto_fixable':i.auto_fixable} for i in issues], 'scanned':len(parsed)}}
            if name == 'free_policy_diff':
                before=args.get('before',{}); after=args.get('after',{})
                return {'ok': True, 'result': {'changed_keys':sorted(set(before.keys()) ^ set(after.keys())), 'before_count':len(before), 'after_count':len(after)}}
            if name == 'free_cron_explain':
                expr=args.get('cron','0 2 * * *')
                presets={'0 2 * * *':'每天 02:00 执行','*/5 * * * *':'每 5 分钟执行','0 8 * * 1-5':'工作日 08:00 执行','0 20 * * *':'每天 20:00 执行'}
                return {'ok': True, 'result': {'cron':expr,'description':presets.get(expr,'自定义 cron 表达式：分 时 日 月 周')}}
            if name == 'free_template_recommender':
                text=args.get('text','')
                intent=RULE_ENGINE.parse_intent(text)
                matches=[{'template_id':k,'text':v} for k,v in STORE.templates.items() if RULE_ENGINE.infer_business(v)==intent.business]
                return {'ok': True, 'result': {'business':intent.business,'matches':matches[:5],'should_save':not matches}}
            if name == 'free_rollback_preview':
                commands=args.get('commands',[])
                rollback=[c.replace(' add ',' del ') if ' add ' in c else c for c in commands]
                return {'ok': True, 'result': {'rollback_commands':rollback,'atomic':True}}
            if name == 'free_anomaly_classifier':
                latency=float(args.get('latency_ms',TELEMETRY.sample(record=False).latency_ms))
                kind='congestion' if latency>50 else 'normal'
                return {'ok': True, 'result': {'type':kind,'confidence':0.88}}
            if name == 'free_healing_advisor':
                kind=args.get('type','congestion')
                action={'congestion':'auto_reroute','link_down':'rollback','anomaly_traffic':'limit'}.get(kind,'observe')
                return {'ok': True, 'result': {'diagnosis':kind,'recommended_action':action}}
            if name == 'free_state_explainer':
                return {'ok': True, 'result': {'summary':'当前系统处于安全仿真模式；模型、规则、工具和工作流均可测试。','active_executions':len(STORE.executions)}}
            if name == 'free_workflow_selector':
                business=args.get('business','video_meeting')
                workflow='cross_domain' if business in {'guest_limiting','lab_isolation'} else 'default'
                return {'ok': True, 'result': {'business':business,'workflow_id':workflow}}
            return {'ok': False, 'error': f'unknown or external tool not connected: {name}', 'dry_run': req.dry_run}
        except Exception as exc:
            return {'ok': False, 'error': str(exc), 'tool_name': name}

TOOLS=ToolRegistry()
