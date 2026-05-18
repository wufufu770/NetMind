import json
from fastapi.testclient import TestClient
from app.main import app
from app.core.model_adapter import MODEL_ADAPTER
from app.core.workflow import ORCHESTRATOR

client = TestClient(app)


def test_closed_loop_calls_model_adapter_for_intent_and_planner(monkeypatch):
    calls = []

    def fake_chat(model_id, messages):
        calls.append({'model_id': model_id, 'messages': messages})
        joined = '\n'.join(m.get('content', '') for m in messages)
        if 'PolicySet' in joined:
            return {'role': 'assistant', 'content': json.dumps({
                'source': 'llm:spy',
                'policies': [{
                    'type': 'qos',
                    'name': 'ai_generated_priority',
                    'action': 'guarantee_bandwidth',
                    'priority': 7,
                    'source': 'llm',
                    'params': {'bandwidth_mbps': 30},
                    'commands': ['tc qdisc add dev s1-eth1 root handle 1: htb'],
                    'rollback_commands': ['tc qdisc del dev s1-eth1 root']
                }]
            }, ensure_ascii=False)}
        if 'IntentDSL' in joined:
            return {'role': 'assistant', 'content': json.dumps({
                'business': 'video_meeting',
                'description': 'AI parsed intent',
                'target': {'src': 'teacher_terminal', 'dst': 'meeting_server', 'traffic_type': 'video'},
                'sla': {'latency_ms': 45, 'packet_loss': 0.005, 'bandwidth_mbps': 30},
                'constraints': {'guest_limit_mbps': 6, 'forbid_guest_to_lab': True},
                'priority': 'critical',
                'recover_policy': 'auto_reroute',
                'rollback_on_failure': True,
                'tags': ['ai_spy']
            }, ensure_ascii=False)}
        return {'role': 'assistant', 'content': '{}'}

    monkeypatch.setattr(MODEL_ADAPTER, 'chat', fake_chat)
    ex = ORCHESTRATOR.run_closed_loop('请用 AI 保障答辩视频会议，延迟低于45ms', dry_run=True)

    assert len(calls) >= 2
    assert ex.intent.business == 'video_meeting'
    assert ex.intent.tags == ['ai_spy']
    assert ex.policy_set.source == 'llm:spy'
    assert ex.policy_set.policies[0].source == 'llm'
    intent_step = next(s for s in ex.steps if s.agent == 'IntentAgent')
    planner_step = next(s for s in ex.steps if s.agent == 'PlannerAgent')
    assert intent_step.tools[0]['name'] == 'model_adapter_chat'
    assert intent_step.tools[0]['fallback'] is False
    assert planner_step.tools[0]['name'] == 'model_adapter_chat'
    assert planner_step.tools[0]['fallback'] is False


def test_closed_loop_falls_back_to_rule_engine_when_model_returns_invalid_json(monkeypatch):
    def bad_chat(model_id, messages):
        return {'role': 'assistant', 'content': 'not json'}

    monkeypatch.setattr(MODEL_ADAPTER, 'chat', bad_chat)
    ex = ORCHESTRATOR.run_closed_loop('访客网络限速5Mbps，并禁止访问实验室服务器', dry_run=True)

    assert ex.intent.business == 'guest_limiting'
    assert ex.policy_set.source.startswith('rule:')
    intent_step = next(s for s in ex.steps if s.agent == 'IntentAgent')
    planner_step = next(s for s in ex.steps if s.agent == 'PlannerAgent')
    assert intent_step.tools[0]['fallback'] is True
    assert planner_step.tools[0]['fallback'] is True
    assert any(t['name'] == 'rule_engine_parse' for t in intent_step.tools)
    assert any(t['name'] == 'rule_engine_match' for t in planner_step.tools)


def test_parse_and_plan_api_use_model_adapter_metadata():
    parsed = client.post('/api/intent/parse', json={'text': '今晚8点保障答辩视频会议，延迟低于50ms'}).json()
    assert parsed['business'] == 'video_meeting'
    planned = client.post('/api/planner/plan', json=parsed).json()
    assert planned['policies']
    assert planned['source'].startswith('llm:') or planned['source'].startswith('rule:')


def test_model_call_history_endpoint_records_workflow_calls():
    before = client.get('/api/config/models/call-history').json()
    client.post('/api/intent/submit', json={'text': '今晚保障答辩视频会议，延迟低于50ms', 'dry_run': True})
    after = client.get('/api/config/models/call-history').json()
    assert len(after) >= len(before)
    assert any('IntentDSL' in row.get('last_user', '') or 'PolicySet' in row.get('last_user', '') for row in after[-6:])


def test_default_mock_workflow_planner_returns_llm_policy_source():
    ex = ORCHESTRATOR.run_closed_loop('今晚8点保障答辩视频会议，教师终端到会议服务器延迟低于50ms，访客网络限速5Mbps', dry_run=True)
    planner_step = next(s for s in ex.steps if s.agent == 'PlannerAgent')
    assert planner_step.tools[0]['name'] == 'model_adapter_chat'
    assert planner_step.tools[0]['fallback'] is False
    assert ex.policy_set.source.startswith('llm:')
    assert all(p.source == 'llm' for p in ex.policy_set.policies)
