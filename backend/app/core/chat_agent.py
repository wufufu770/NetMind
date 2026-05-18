
from __future__ import annotations
from typing import Dict, Any
from ..store import STORE
from .telemetry import TELEMETRY
from .topology import TOPOLOGY

class ConversationAgent:
    """Read-only network assistant with grounded runtime context."""
    def answer(self, question: str) -> Dict[str, Any]:
        q=question.lower()
        latest = STORE.telemetry[-1] if STORE.telemetry else TELEMETRY.sample()
        context = {
            'executions': len(STORE.executions),
            'latest_latency_ms': latest.latency_ms,
            'latest_packet_loss': latest.packet_loss,
            'alerts': len([t for t in STORE.telemetry[-20:] if t.alert]),
            'topology_nodes': len(TOPOLOGY.snapshot()['nodes']),
            'pending_approvals': len([a for a in STORE.approvals.values() if a.status=='pending']),
        }
        if '为什么' in question or 'why' in q or '原因' in question:
            answer = f"当前主要判断依据是最近遥测延迟 {latest.latency_ms}ms、丢包 {latest.packet_loss}，以及拓扑可达性正常。若出现拥塞，系统会优先启用备用路径。"
        elif '状态' in question or '健康' in question or 'status' in q:
            answer = f"当前网络处于可用状态：最近延迟 {latest.latency_ms}ms，活跃执行 {context['executions']} 条，待审批 {context['pending_approvals']} 条。"
        elif '配置' in question or '策略' in question:
            answer = f"系统已加载 {len(STORE.rules)} 条规则、{len(STORE.tools)} 个工具、{len(STORE.agents)} 个 Agent。策略下发前会经过冲突检测、安全检查和回滚计划生成。"
        else:
            answer = "我只能读取系统状态、意图执行、策略验证、遥测、自愈和配置含义，不会直接执行网络变更。"
        STORE.log('chat', question, 'info', data={'answer': answer})
        return {'answer': answer, 'context': context, 'read_only': True}

CHAT_AGENT = ConversationAgent()
