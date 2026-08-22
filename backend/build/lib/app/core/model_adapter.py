from __future__ import annotations
import json, os, re, time
from typing import Any, Dict, List, Tuple
import httpx
from pydantic import ValidationError
from ..schemas import IntentDSL, Policy, PolicySet
from ..store import STORE

class ModelAdapter:
    """OpenAI-compatible model adapter used by the actual workflow.

    The previous build only used this adapter for config connection tests and
    chat.  This version exposes structured helpers for IntentAgent and
    PlannerAgent so the closed-loop workflow can use the model bound to each
    Agent, with deterministic safe fallback to the rule engine when the model is
    unavailable or returns invalid JSON.
    """
    def __init__(self):
        self.call_history: List[Dict[str, Any]] = []

    def _api_key(self, model_id: str) -> str | None:
        return os.getenv(f'NETMIND_API_KEY_{model_id.upper()}') or os.getenv('OPENAI_API_KEY')

    def agent_model_id(self, agent_name: str, default: str = 'mock') -> str:
        agent = STORE.agents.get(agent_name)
        return (agent.model_id if agent and agent.model_id else default) or default

    def _record_call(self, model_id: str, messages: List[Dict[str, str]], mode: str) -> None:
        self.call_history.append({
            'model_id': model_id,
            'mode': mode,
            'message_count': len(messages),
            'last_user': next((m.get('content','') for m in reversed(messages) if m.get('role') == 'user'), '')[:240]
        })
        if len(self.call_history) > 200:
            self.call_history = self.call_history[-200:]

    def test(self, model_id: str):
        cfg=STORE.models.get(model_id)
        if not cfg: return {'ok': False, 'error': 'model not found'}
        if cfg.base_url.startswith('local://') or cfg.id == 'mock':
            return {'ok': True, 'latency_ms': 8, 'model': cfg.model_id, 'mode': 'mock'}
        key=self._api_key(model_id)
        if not key:
            return {'ok': False, 'model': cfg.model_id, 'error': f'missing NETMIND_API_KEY_{model_id.upper()}'}
        started=time.time()
        try:
            with httpx.Client(timeout=8) as client:
                res=client.post(cfg.base_url.rstrip('/') + '/chat/completions', headers={'Authorization':f'Bearer {key}'}, json={'model':cfg.model_id,'messages':[{'role':'user','content':'ping'}],'max_tokens':8,'temperature':0})
                ok=res.status_code < 400
                cfg.online=ok
                return {'ok': ok, 'latency_ms': int((time.time()-started)*1000), 'model': cfg.model_id, 'status_code': res.status_code}
        except Exception as exc:
            cfg.online=False
            return {'ok': False, 'model': cfg.model_id, 'error': str(exc)}

    def chat(self, model_id: str, messages: List[Dict[str, str]]):
        cfg=STORE.models.get(model_id) or STORE.models.get('mock')
        if not cfg:
            return {'role':'assistant','content':'模型配置不存在，已切换为规则/离线模式。'}
        if cfg.id == 'mock' or cfg.base_url.startswith('local://'):
            self._record_call(model_id, messages, 'mock')
            return {'role':'assistant','content':self._mock_structured_response(messages)}
        key=self._api_key(model_id)
        if not key:
            self._record_call(model_id, messages, 'missing_key')
            return {'role':'assistant','content':'模型未配置 API Key，已切换为规则/离线模式。'}
        try:
            self._record_call(model_id, messages, 'remote')
            with httpx.Client(timeout=20) as client:
                res=client.post(cfg.base_url.rstrip('/') + '/chat/completions', headers={'Authorization':f'Bearer {key}'}, json={'model':cfg.model_id,'messages':messages,'max_tokens':cfg.max_tokens,'temperature':cfg.temperature})
                res.raise_for_status()
                data=res.json()
                return data['choices'][0]['message']
        except Exception as exc:
            return {'role':'assistant','content':f'模型调用失败，已降级：{exc}'}

    def _mock_structured_response(self, messages: List[Dict[str, str]]) -> str:
        text='\n'.join(m.get('content','') for m in messages)
        # Planner prompts include the serialized IntentDSL payload, so PolicySet
        # must be checked before IntentDSL. Otherwise mock planning accidentally
        # returns an IntentDSL object and the workflow falls back to rules.
        if 'PolicySet' in text or 'policy set' in text.lower() or '策略集' in text:
            return json.dumps(self._mock_policy_json(text), ensure_ascii=False)
        if 'IntentDSL' in text or 'intent dsl' in text.lower() or 'intent schema' in text.lower():
            return json.dumps(self._mock_intent_json(text), ensure_ascii=False)
        return 'Mock response: 当前网络健康，建议先处理 ACL 优先级冲突。'

    def _mock_intent_json(self, text: str) -> Dict[str, Any]:
        from .rule_engine import RULE_ENGINE
        intent=RULE_ENGINE.parse_intent(text)
        return intent.model_dump()

    def _mock_policy_json(self, text: str) -> Dict[str, Any]:
        from .rule_engine import RULE_ENGINE
        intent=RULE_ENGINE.parse_intent(text)
        return RULE_ENGINE.plan(intent).model_dump()

    def _extract_json(self, content: str) -> Any:
        content = content.strip()
        # Strip markdown JSON fences if present.
        fence = re.search(r'```(?:json)?\s*(.*?)```', content, re.S | re.I)
        if fence:
            content = fence.group(1).strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start_candidates=[i for i in [content.find('{'), content.find('[')] if i >= 0]
            if not start_candidates:
                raise
            start=min(start_candidates)
            end=max(content.rfind('}'), content.rfind(']'))
            if end <= start:
                raise
            return json.loads(content[start:end+1])

    def parse_intent(self, text: str, agent_name: str='IntentAgent') -> Tuple[IntentDSL | None, Dict[str, Any]]:
        model_id=self.agent_model_id(agent_name)
        agent=STORE.agents.get(agent_name)
        prompt=(agent.prompt if agent else '')
        messages=[
            {'role':'system','content':(prompt+'\n你是 IntentAgent。只输出符合 IntentDSL schema 的 JSON，不要解释。字段必须包含 business,target,sla,constraints,priority,recover_policy,rollback_on_failure。')},
            {'role':'user','content':f'将以下自然语言网络意图解析为 IntentDSL JSON：\n{text}'}
        ]
        msg=self.chat(model_id, messages)
        content=msg.get('content','') if isinstance(msg, dict) else str(msg)
        meta={'agent':agent_name,'model_id':model_id,'raw_content':content,'used_model':True,'fallback':False}
        try:
            data=self._extract_json(content)
            if isinstance(data, dict) and 'intent' in data and isinstance(data['intent'], dict):
                data=data['intent']
            intent=IntentDSL(**data)
            if not intent.description:
                intent.description=text[:120]
            return intent, meta
        except Exception as exc:
            meta.update({'fallback':True,'error':str(exc)})
            return None, meta

    def plan_policy(self, intent: IntentDSL, agent_name: str='PlannerAgent', tool_context: Dict[str, Any] | None=None) -> Tuple[PolicySet | None, Dict[str, Any]]:
        model_id=self.agent_model_id(agent_name)
        payload=intent.model_dump(mode='json')
        agent=STORE.agents.get(agent_name)
        prompt=(agent.prompt if agent else '')
        context_text=json.dumps(tool_context or {}, ensure_ascii=False)
        messages=[
            {'role':'system','content':(prompt+'\n你是 PlannerAgent。必须优先参考工具上下文，再输出符合 PolicySet schema 的 JSON，不要解释。每条 policy 必须包含 type,name,action,priority,source,params,commands,rollback_commands。source 必须为 llm 或 rule。')},
            {'role':'user','content':'工具上下文 ToolContext：\n'+context_text+'\n基于以下 IntentDSL 生成 PolicySet 策略集 JSON：\n'+json.dumps(payload, ensure_ascii=False)}
        ]
        msg=self.chat(model_id, messages)
        content=msg.get('content','') if isinstance(msg, dict) else str(msg)
        meta={'agent':agent_name,'model_id':model_id,'raw_content':content,'used_model':True,'fallback':False}
        try:
            data=self._extract_json(content)
            if isinstance(data, dict) and 'policy_set' in data and isinstance(data['policy_set'], dict):
                data=data['policy_set']
            if isinstance(data, list):
                data={'intent_id':intent.intent_id,'policies':data,'source':f'llm:{model_id}'}
            data.setdefault('intent_id', intent.intent_id)
            ps=PolicySet(**data)
            # Preserve original intent_id even if the model invented one.
            ps.intent_id=intent.intent_id
            for p in ps.policies:
                if p.source == 'rule':
                    p.source='llm'
            if not ps.source.startswith('llm'):
                ps.source=f'llm:{model_id}'
            return ps, meta
        except Exception as exc:
            meta.update({'fallback':True,'error':str(exc)})
            return None, meta
MODEL_ADAPTER=ModelAdapter()
