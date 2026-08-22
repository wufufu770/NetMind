from __future__ import annotations
from typing import List
from ..schemas import IntentDSL, Policy, PolicySet
from ..store import STORE
from .topology import TOPOLOGY

BUSINESS_KEYWORDS=[
    ('video_meeting',['答辩','会议','视频','meeting']),
    ('guest_limiting',['访客','来宾','guest']),
    ('lab_isolation',['实验室','lab']),
    ('backup',['备份','backup']),
    ('exam',['考试','exam']),
    ('live_stream',['直播','推流']),
]

COOKIE_BASE='0x4e65744d'

class RuleEngine:
    def infer_business(self, text: str) -> str:
        t=text.lower()
        for biz, kws in BUSINESS_KEYWORDS:
            if any(k.lower() in t for k in kws): return biz
        return 'default'

    def parse_intent(self, text: str) -> IntentDSL:
        business=self.infer_business(text)
        latency=50 if '50' in text or '低于' in text else 80
        guest_limit=5 if '5' in text or '访客' in text else None
        intent=IntentDSL(business=business, description=text[:120])
        if '凌晨' in text or '2点' in text:
            intent.constraints.time_range={'start':'02:00','end':'04:00'}
            intent.priority='medium'
        if 'critical' in text or '紧急' in text:
            intent.priority='critical'
        intent.sla.latency_ms=latency
        intent.constraints.guest_limit_mbps=guest_limit
        return intent

    def match(self, intent: IntentDSL) -> List[str]:
        hits=[]
        for name, rule in sorted(STORE.rules.items(), key=lambda kv: kv[1].priority, reverse=True):
            if not rule.enabled: continue
            if rule.match_business == intent.business or rule.match_business == 'default':
                hits.append(name)
            if len(hits)>=4: break
        return hits

    def _egress(self, intent: IntentDSL) -> tuple[str,str]:
        path=TOPOLOGY.path(intent.target.src, intent.target.dst) or []
        switches=set(TOPOLOGY.switches())
        sw=next((n for n in path if n in switches), None)
        if sw is None:
            all_sw=TOPOLOGY.switches()
            sw=all_sw[0] if all_sw else 's1'
        return sw, f'{sw}-eth1'

    def plan(self, intent: IntentDSL) -> PolicySet:
        hits=self.match(intent)
        sw, ingress=self._egress(intent)
        backup_sw=next((s for s in TOPOLOGY.switches() if s!=sw), sw)
        guest_subnet=TOPOLOGY.node_attr('guest_terminal','subnet','192.168.10.0/24')
        lab_ip=TOPOLOGY.node_attr('lab_server','ip','10.0.0.2')
        policies=[]
        if intent.business in ['video_meeting','meeting_wifi','voip']:
            policies.append(Policy(type='qos', name='video_priority', action='guarantee_bandwidth', priority=10, source='rule', params={'src':intent.target.src,'dst':intent.target.dst,'bandwidth_mbps':intent.sla.bandwidth_mbps or 20,'queue':5}, commands=[f"tc qdisc add dev {ingress} root handle 1: htb", f"ovs-ofctl add-flow {sw} cookie={COOKIE_BASE}00000001,priority=500,ip,actions=normal"], rollback_commands=[f'tc qdisc del dev {ingress} root', f'ovs-ofctl del-flows {sw} cookie={COOKIE_BASE}00000001/-1']))
            policies.append(Policy(type='route', name='backup_path', action='prefer_path', priority=20, source='rule', params={'path':[sw,backup_sw],'trigger_latency_ms':intent.sla.latency_ms or 50}, commands=[f"ovs-ofctl add-flow {sw} cookie={COOKIE_BASE}00000002,priority=450,actions=normal"], rollback_commands=[f'ovs-ofctl del-flows {sw} cookie={COOKIE_BASE}00000002/-1']))
        if intent.constraints.guest_limit_mbps or intent.business == 'guest_limiting':
            policies.append(Policy(type='acl', name='guest_isolation', action='deny_guest_to_lab', priority=30, source='rule', params={'src':'guest_terminal','dst':'lab_server'}, commands=[f'iptables -A FORWARD -s {guest_subnet} -d {lab_ip} -j DROP'], rollback_commands=[f'iptables -D FORWARD -s {guest_subnet} -d {lab_ip} -j DROP']))
            policies.append(Policy(type='qos', name='guest_limit', action='limit_bandwidth', priority=40, source='rule', params={'limit_mbps':intent.constraints.guest_limit_mbps or 5}, commands=[f'tc class add dev {ingress} parent 1: classid 1:30 htb rate 5mbit'], rollback_commands=[f'tc class del dev {ingress} classid 1:30']))
        if intent.business == 'lab_isolation':
            policies.append(Policy(type='acl', name='lab_only_teacher', action='allow_teacher_only', priority=5, source='rule', params={'allowed_src':'teacher_terminal','dst':'lab_server'}, commands=[f'iptables -A FORWARD -d {lab_ip} -j DROP'], rollback_commands=[f'iptables -D FORWARD -d {lab_ip} -j DROP']))
        if not policies:
            policies.append(Policy(type='route', name='best_effort', action='normal', priority=100, source='rule', params={}, commands=[f'ovs-ofctl dump-flows {sw}'], rollback_commands=[]))
        return PolicySet(intent_id=intent.intent_id, policies=policies, source='rule:'+','.join(hits[:3]))

RULE_ENGINE=RuleEngine()
