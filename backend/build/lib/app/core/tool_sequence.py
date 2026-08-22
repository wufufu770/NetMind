
from __future__ import annotations
from typing import Dict, Any, List
from ..schemas import Execution

class ToolSequenceBuilder:
    def from_execution(self, ex: Execution) -> Dict[str, Any]:
        seq=[]
        offset=0
        for idx, step in enumerate(ex.steps, start=1):
            duration=max(step.duration_ms, 1)
            tools=step.tools or [{'name':'no_tool','arguments':{},'result':'not required'}]
            for t in tools:
                seq.append({
                    'index': len(seq)+1,
                    'agent': step.agent,
                    'tool': t.get('name','unknown'),
                    'status': step.status.value if hasattr(step.status,'value') else str(step.status),
                    'start_ms': offset,
                    'duration_ms': duration,
                    'input_keys': list(step.input.keys()) if isinstance(step.input, dict) else [],
                    'output_keys': list(step.output.keys()) if isinstance(step.output, dict) else [],
                    'summary': f"{step.agent} 调用 {t.get('name','unknown')}，耗时 {duration}ms",
                })
                offset += duration
        return {'execution_id': ex.execution_id, 'total_duration_ms': offset, 'items': seq}

TOOL_SEQUENCE = ToolSequenceBuilder()
