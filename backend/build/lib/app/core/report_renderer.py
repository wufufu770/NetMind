
from __future__ import annotations
from html import escape
from .report import REPORTER

class ReportRenderer:
    def html(self, ex):
        md=REPORTER.markdown(ex)
        body='\n'.join(f'<p>{escape(line)}</p>' if line and not line.startswith('#') else f'<h2>{escape(line.lstrip("# "))}</h2>' for line in md.splitlines())
        return f'<!doctype html><html><head><meta charset="utf-8"><title>{escape(ex.execution_id)}</title><style>body{{font-family:Arial,sans-serif;margin:40px;color:#111}}h2{{border-bottom:1px solid #ddd;padding-bottom:6px}}p{{line-height:1.5}}</style></head><body>{body}</body></html>'
    def pdf_bytes(self, ex):
        # Minimal but valid single-page PDF payload for dependency-free export.
        text=REPORTER.markdown(ex)[:1500].replace('\\','\\\\').replace('(','\\(').replace(')','\\)').replace('\n','\\n')
        stream=f'BT /F1 9 Tf 40 800 Td ({text}) Tj ET'
        pdf=f'%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n4 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\ntrailer << /Root 1 0 R /Size 6 >>\n%%EOF\n'
        return pdf.encode('latin-1','ignore')

REPORT_RENDERER=ReportRenderer()
