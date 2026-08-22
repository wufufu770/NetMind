from __future__ import annotations
from ..schemas import Execution
from datetime import datetime

class ReportGenerator:
    def markdown(self, ex: Execution) -> str:
        intent=ex.intent
        lines=[f'# NetMind 执行报告：{ex.execution_id}', '', f'- 生成时间：{datetime.utcnow().isoformat()}Z', f'- 状态：{ex.status}', '']
        if intent:
            lines += ['## 1. 意图摘要', f'- 业务场景：`{intent.business}`', f'- 描述：{intent.description}', f'- 目标：{intent.target.src} → {intent.target.dst}', f'- SLA：延迟≤{intent.sla.latency_ms}ms，丢包≤{intent.sla.packet_loss}', '']
        if ex.policy_set:
            lines += ['## 2. 策略集']
            for p in ex.policy_set.policies:
                lines.append(f'- **{p.type}/{p.name}**：{p.action}，source={p.source}')
            lines.append('')
        if ex.verification:
            lines += ['## 3. 验证结果', f'- 通过：{ex.verification.passed}', f'- 可达性：{ex.verification.reachable}', f'- SLA 置信度：{ex.verification.sla_confidence}', '']
            for issue in ex.verification.conflicts: lines.append(f'- {issue.severity} {issue.code}: {issue.message}')
            lines.append('')
        if ex.deploy:
            lines += ['## 4. 下发与回滚', f'- 成功：{ex.deploy.success}', f'- 回滚：{ex.deploy.rolled_back}', '']
            for c in ex.deploy.executed: lines.append(f'  - `{c.command}` → {c.output}')
            lines.append('')
        if ex.healing:
            h=ex.healing
            lines += ['## 5. 自愈结果', f'- 动作：{h.action_taken}', f'- 前：{h.before_snapshot.latency_ms}ms / loss {h.before_snapshot.packet_loss}', f'- 后：{h.after_snapshot.latency_ms}ms / loss {h.after_snapshot.packet_loss}', f'- 结论：{h.summary}', '']
        lines += ['## 6. Agent 执行链路']
        for s in ex.steps: lines.append(f'- {s.agent}: {s.status} ({s.duration_ms}ms)')
        return '\n'.join(lines)+'\n'
REPORTER=ReportGenerator()
