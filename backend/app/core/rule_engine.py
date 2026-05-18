from __future__ import annotations
from typing import List
from ..schemas import IntentDSL, Policy, PolicySet
from ..store import STORE

class RuleEngine:
    def infer_business(self, text: str) -> str:
        t=text.lower()
        if any(k in text for k in ['答辩','会议','视频','meeting']): return 'video_meeting'
        if any(k in text for k in ['访客','来宾','guest']): return 'guest_limiting'
        if any(k in text for k in ['实验室','lab']): return 'lab_isolation'
        if any(k in text for k in ['备份','backup']): return 'backup'
        if any(k in text for k in ['考试','exam']): return 'exam'
        if any(k in text for k in ['直播','推流']): return 'live_stream'
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

    def plan(self, intent: IntentDSL) -> PolicySet:
        hits=self.match(intent)
        policies=[]
        if intent.business in ['video_meeting','meeting_wifi','voip']:
            policies.append(Policy(type='qos', name='video_priority', action='guarantee_bandwidth', priority=10, source='rule', params={'src':intent.target.src,'dst':intent.target.dst,'bandwidth_mbps':intent.sla.bandwidth_mbps or 20,'queue':5}, commands=[f"tc qdisc add dev s1-eth1 root handle 1: htb", f"ovs-ofctl add-flow s1 cookie=0x4e65744d00000001,priority=500,ip,actions=normal"], rollback_commands=['tc qdisc del dev s1-eth1 root','ovs-ofctl del-flows s1 cookie=0x4e65744d00000001/-1']))
            policies.append(Policy(type='route', name='backup_path', action='prefer_path', priority=20, source='rule', params={'path':['s1','s2'],'trigger_latency_ms':intent.sla.latency_ms or 50}, commands=['ovs-ofctl add-flow s1 cookie=0x4e65744d00000002,priority=450,actions=normal'], rollback_commands=['ovs-ofctl del-flows s1 cookie=0x4e65744d00000002/-1']))
        if intent.constraints.guest_limit_mbps or intent.business == 'guest_limiting':
            policies.append(Policy(type='acl', name='guest_isolation', action='deny_guest_to_lab', priority=30, source='rule', params={'src':'guest_terminal','dst':'lab_server'}, commands=['iptables -A FORWARD -s 192.168.10.0/24 -d 10.0.0.2 -j DROP'], rollback_commands=['iptables -D FORWARD -s 192.168.10.0/24 -d 10.0.0.2 -j DROP']))
            policies.append(Policy(type='qos', name='guest_limit', action='limit_bandwidth', priority=40, source='rule', params={'limit_mbps':intent.constraints.guest_limit_mbps or 5}, commands=['tc class add dev s1-eth3 parent 1: classid 1:30 htb rate 5mbit'], rollback_commands=['tc class del dev s1-eth3 classid 1:30']))
        if intent.business == 'lab_isolation':
            policies.append(Policy(type='acl', name='lab_only_teacher', action='allow_teacher_only', priority=5, source='rule', params={'allowed_src':'teacher_terminal','dst':'lab_server'}, commands=['iptables -A FORWARD -d 10.0.0.2 -j DROP'], rollback_commands=['iptables -D FORWARD -d 10.0.0.2 -j DROP']))
        if not policies:
            policies.append(Policy(type='route', name='best_effort', action='normal', priority=100, source='rule', params={}, commands=['ovs-ofctl dump-flows s1'], rollback_commands=[]))
        return PolicySet(intent_id=intent.intent_id, policies=policies, source='rule:'+','.join(hits[:3]))

RULE_ENGINE=RuleEngine()
