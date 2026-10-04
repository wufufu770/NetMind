
from __future__ import annotations
from html import escape
from .report import REPORTER

class ReportRenderer:
    def html(self, ex):
        md=REPORTER.markdown(ex)
        body='\n'.join(f'<p>{escape(line)}</p>' if line and not line.startswith('#') else f'<h2>{escape(line.lstrip("# "))}</h2>' for line in md.splitlines())
        return f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(ex.execution_id)}</title><style>body{{font-family:Arial,sans-serif;margin:40px;color:#111}}h2{{border-bottom:1px solid #ddd;padding-bottom:6px}}p{{line-height:1.5}}</style></head><body>{body}</body></html>'
REPORT_RENDERER=ReportRenderer()
