from __future__ import annotations
from datetime import datetime, timezone

SEVERITY_ORDER={'error':0,'warning':1,'info':2}

def render_json(report: dict) -> str:
    import json as _json
    return _json.dumps(report, ensure_ascii=False, indent=2)

def render_md(report: dict) -> str:
    lines=[
        f"# NetMind Diagnose Report: {report['topology']}",
        '',
        f"- 生成时间：{report['generated_at']}",
        f"- 模式：`{report['mode']}`",
        f"- 规模：{report['node_count']} nodes / {report['link_count']} links",
        f"- 结论：**{report['summary']}**",
        '',
    ]
    if not report['findings']:
        lines += ['## Findings', '', 'No issues found. 结构检查全部通过。', '']
    else:
        lines += ['## Findings', '']
        for f in report['findings']:
            icon={'error':'ERROR','warning':'WARN','info':'INFO'}[f['severity']]
            lines.append(f"### [{icon}] {f['title']} `{f['id']}`")
            if f.get('detail'):
                lines.append(f['detail'])
            lines.append('')
    if report.get('llm'):
        llm=report['llm']
        lines += ['## LLM Root-cause Analysis']
        if 'analysis' in llm:
            lines += [f"_model: {llm.get('model')}{' (cached)' if llm.get('cached') else ''}_", '', llm['analysis'], '']
        else:
            lines += [f"> LLM enhancement skipped: {llm.get('skipped')}", '']
    return '\n'.join(lines)
