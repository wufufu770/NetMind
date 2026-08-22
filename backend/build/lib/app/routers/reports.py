from __future__ import annotations
from fastapi import APIRouter, Body
from fastapi.responses import PlainTextResponse, HTMLResponse, Response
from ..schemas import ReportOptions
from ..core.report import REPORTER
from .common import get_execution

router = APIRouter()

@router.post('/api/report/generate', response_class=PlainTextResponse)
def generate_report(execution_id: str = Body(..., embed=True)):
    ex=get_execution(execution_id)
    return REPORTER.markdown(ex)

@router.get('/api/report/{execution_id}.html', response_class=HTMLResponse)
def report_html(execution_id: str):
    md=REPORTER.markdown(get_execution(execution_id))
    return '<html><body><pre>'+md.replace('&','&amp;').replace('<','&lt;')+'</pre></body></html>'

@router.get('/api/report/{execution_id}.md', response_class=PlainTextResponse)
def report_md(execution_id: str):
    return REPORTER.markdown(get_execution(execution_id))

@router.get('/api/report/{execution_id}.json')
def report_json(execution_id: str):
    return get_execution(execution_id).model_dump(mode='json')

@router.post('/api/report/generate/options', response_class=PlainTextResponse)
def generate_report_with_options(options: ReportOptions):
    ex=get_execution(options.execution_id)
    return REPORTER.markdown(ex)

@router.get('/api/report/{execution_id}/bundle')
def report_bundle(execution_id: str):
    ex=get_execution(execution_id)
    md=REPORTER.markdown(ex)
    return {'execution_id':execution_id,'markdown':md,'html':'<pre>'+md+'</pre>','json':ex.model_dump(mode='json')}

@router.get('/api/report/{execution_id}.pdf')
def report_pdf(execution_id: str):
    md=REPORTER.markdown(get_execution(execution_id))[:1800]
    safe=md.replace('\\','\\\\').replace('(','\\(').replace(')','\\)').replace('\n','\\n')
    pdf=f"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n4 0 obj << /Length {len(safe)+64} >> stream\nBT /F1 10 Tf 40 800 Td ({safe}) Tj ET\nendstream endobj\n5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\nxref\n0 6\n0000000000 65535 f \ntrailer << /Root 1 0 R /Size 6 >>\nstartxref\n0\n%%EOF\n"
    return Response(content=pdf.encode('latin-1','ignore'), media_type='application/pdf', headers={'Content-Disposition':f'attachment; filename="{execution_id}.pdf"'})

@router.get('/api/report/{execution_id}/rich.html', response_class=HTMLResponse)
def report_rich_html(execution_id: str):
    from ..core.report_renderer import REPORT_RENDERER
    return REPORT_RENDERER.html(get_execution(execution_id))

@router.get('/api/report/{execution_id}/rich.pdf')
def report_rich_pdf(execution_id: str):
    from ..core.report_renderer import REPORT_RENDERER
    return Response(content=REPORT_RENDERER.pdf_bytes(get_execution(execution_id)), media_type='application/pdf', headers={'Content-Disposition':f'attachment; filename="{execution_id}-rich.pdf"'})
