from __future__ import annotations
from fastapi import APIRouter, Response, Body
from fastapi.responses import PlainTextResponse, HTMLResponse, Response, JSONResponse
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

def _pdf_response(markdown: str, *, filename: str):
    """PDF 响应。缺 CJK 字体时返回 422 并说清修法。

    绝不返回一个「生成了但内容被静默丢弃」的 PDF——那正是此前手写实现的
    问题：用户拿到一份几乎没有内容的文档，**且没有任何报错**。
    """
    from ..core.pdf_export import PdfFontUnavailable, markdown_to_pdf
    try:
        data = markdown_to_pdf(markdown, title=filename)
    except PdfFontUnavailable as exc:
        return JSONResponse(status_code=422, content={'error': str(exc)})
    return Response(content=data, media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@router.get('/api/report/{execution_id}.pdf')
def report_pdf(execution_id: str):
    return _pdf_response(REPORTER.markdown(get_execution(execution_id)),
                         filename=f'{execution_id}.pdf')


@router.get('/api/report/{execution_id}/rich.html', response_class=HTMLResponse)
def report_rich_html(execution_id: str):
    from ..core.report_renderer import REPORT_RENDERER
    return REPORT_RENDERER.html(get_execution(execution_id))

@router.get('/api/report/{execution_id}/rich.pdf')
def report_rich_pdf(execution_id: str):
    from ..core.report_renderer import REPORT_RENDERER
    return _pdf_response(REPORTER.markdown(get_execution(execution_id)),
                         filename=f'{execution_id}-rich.pdf')
