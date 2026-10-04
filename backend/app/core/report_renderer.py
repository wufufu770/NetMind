
from __future__ import annotations
from html import escape
from .report import REPORTER

class ReportRenderer:
    """markdown → HTML 的最小渲染。

    第一版是一行三元表达式：

        f'<p>…</p>' if line and not line.startswith('#') else f'<h2>…</h2>'

    两个问题，都实测过：
      ① **空行也落进 else 分支** —— markdown 里每节之间都有空行，于是每个
         空行都渲染成一个空的 `<h2></h2>`。看起来像报告缺了内容。
      ② `#` 与 `##` 全被拍平成 `<h2>`，标题层级丢失。

    现在按行首 `#` 的个数决定标题级别，空行直接跳过。
    """
    def html(self, ex):
        parts = []
        for line in REPORTER.markdown(ex).splitlines():
            if not line.strip():
                continue                      # 空行不是内容，不该变成一个空标题
            if line.lstrip().startswith('#'):
                level = min(len(line) - len(line.lstrip('#')), 3)
                text = line.lstrip('#').strip()
                parts.append(f'<h{level}>{escape(text)}</h{level}>')
            else:
                parts.append(f'<p>{escape(line)}</p>')
        body = '\n'.join(parts)
        return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                f'<title>{escape(ex.execution_id)}</title>'
                '<style>body{font-family:Arial,sans-serif;margin:40px;color:#111}'
                'h1{font-size:22px}h2{font-size:17px;border-bottom:1px solid #ddd;padding-bottom:6px}'
                'p{line-height:1.5}</style></head>'
                f'<body>{body}</body></html>')

REPORT_RENDERER=ReportRenderer()
