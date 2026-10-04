"""PDF 导出的诚实性回归。

此前两条 PDF 路径各自手写了一份最小 PDF，用 `latin-1` + `ignore` 编码。
实测后果：报告正文是中文，而 base-14 的 Helvetica 只能表示 Latin-1，
于是**每一个汉字都被静默丢弃**。用 `pdftotext` 读生成的文件拿到的是：

    # NetMind exec-…- Status.success## 1.  - video_meeting

而 markdown 原文是：

    ## 1. 意图摘要 / - 描述：给会议网提高优先级

**用户导出 PDF 得到一份几乎没有内容的文档，且没有任何报错。**
另外 xref 表是假的（`startxref 0`），严格校验器会拒绝该文件。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core import pdf_export
from app.core.pdf_export import (FONT_ENV, PdfFontUnavailable, has_cjk,
                                markdown_to_pdf)

CHINESE_MD = """# NetMind 执行报告：exec-1

- 描述：给会议网提高优先级
- 目标：teacher_terminal → meeting_server
"""


def _extracted_text(pdf_bytes: bytes) -> str:
    """从 PDF 里取回文本。有 pdftotext 就用它（真实解析器），否则退到流里的原始字节。"""
    import re
    import subprocess
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            f.write(pdf_bytes)
            path = f.name
        try:
            r = subprocess.run(['pdftotext', path, '-'], capture_output=True,
                               text=True, timeout=60)
            if r.returncode == 0:
                return r.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        finally:
            os.unlink(path)
    except Exception:
        pass
    m = re.search(rb'stream\n(.*?)\nendstream', pdf_bytes, re.S)
    return (m.group(1).decode('latin-1', 'ignore') if m else '')


# ---------- 中文字符必须保住 ----------

def test_chinese_survives_the_pdf():
    """这条是本文件存在的全部理由。"""
    pdf = markdown_to_pdf(CHINESE_MD)
    assert pdf[:5] == b'%PDF-'
    text = _extracted_text(pdf)
    for token in ('执行报告', '描述', '给会议网提高优先级', '目标', 'teacher_terminal'):
        assert token in text, f'PDF 里找不到「{token}」。实际读出：\n{text[:300]}'


def test_chinese_is_not_silently_dropped_by_encoding():
    """生成过程里不能有任何一步把汉字丢掉。"""
    pdf = markdown_to_pdf(CHINESE_MD)
    assert len(pdf) > 5000, (
        f'PDF 只有 {len(pdf)} 字节——大概率是汉字被丢掉、只剩骨架')


def test_ascii_only_content_needs_no_cjk_font():
    """纯 ASCII 内容不该被字体问题挡住——那会让报告功能整体不可用。"""
    pdf = markdown_to_pdf('# Report\n\n- item: 1\n')
    assert pdf[:5] == b'%PDF-'
    assert 'Report' in _extracted_text(pdf)


def test_long_lines_wrap_instead_of_running_off_the_page():
    pdf = markdown_to_pdf('x' * 4000)
    assert pdf[:5] == b'%PDF-'
    assert b'/Count' in pdf or b'/Type /Pages' in pdf


def test_empty_content_still_produces_a_pdf():
    pdf = markdown_to_pdf('')
    assert pdf[:5] == b'%PDF-'


# ---------- 缺字体：明确报错，不产出残缺文件 ----------

def test_missing_font_raises_instead_of_emitting_a_mutilated_pdf(monkeypatch):
    """这是原缺陷的核心：不能一边丢内容一边返回成功。"""
    monkeypatch.setattr(pdf_export, 'register_cjk_font', lambda: None)
    with pytest.raises(PdfFontUnavailable) as e:
        markdown_to_pdf(CHINESE_MD)
    msg = str(e.value)
    assert 'CJK' in msg or '字体' in msg
    assert FONT_ENV in msg, '报错要说清怎么修（装字体或指定路径）'
    assert '.md' in msg, '报错要指出还有哪条路可走'


def test_font_override_env_is_honoured(monkeypatch, tmp_path):
    fake = tmp_path / 'fake.ttc'
    fake.write_bytes(b'not-a-real-font')
    monkeypatch.setenv(FONT_ENV, str(fake))
    assert pdf_export.candidate_fonts() == [str(fake)]


def test_candidate_fonts_skips_nonexistent(monkeypatch):
    monkeypatch.setenv(FONT_ENV, '/nowhere/none.ttf')
    assert pdf_export.candidate_fonts() == [], '指向不存在的文件时应返回空，不该崩溃'


def test_has_cjk():
    assert has_cjk('中文')
    assert has_cjk('a中b')
    assert not has_cjk('plain ascii 123')
    assert not has_cjk('café')


# ---------- 端点行为 ----------

def _client(monkeypatch):
    for k in ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_RATE_LIMIT'):
        monkeypatch.delenv(k, raising=False)
    import app.core.access as _access
    monkeypatch.setattr(_access, '_client_host', lambda r: '127.0.0.1')
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _eid(c) -> str:
    """自己造一条执行。跳过等于没测。"""
    r = c.post('/api/intent/submit', json={'text': '给会议网提高优先级', 'dry_run': True})
    assert r.status_code == 200, r.text[:200]
    return r.json()['execution_id']


def test_pdf_endpoint_returns_a_real_pdf(monkeypatch):
    c = _client(monkeypatch)
    eid = _eid(c)
    r = c.get(f'/api/report/{eid}.pdf')
    assert r.status_code == 200
    assert r.content[:5] == b'%PDF-'
    assert '执行报告' in _extracted_text(r.content)


def test_pdf_endpoint_answers_422_when_no_font(monkeypatch):
    """没有中文字体时：422 + 修法说明，不是 200 + 残缺文件。"""
    c = _client(monkeypatch)
    eid = _eid(c)
    monkeypatch.setattr(pdf_export, 'register_cjk_font', lambda: None)
    r = c.get(f'/api/report/{eid}.pdf')
    assert r.status_code == 422, f'缺字体却返回 {r.status_code}——残缺 PDF 又回来了'
    assert '字体' in r.json()['error']


def test_rich_pdf_uses_the_same_exporter():
    """两条 PDF 路径此前各写一份手写实现；现在必须走同一处，否则会再次漂移。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'app' / 'routers' / 'reports.py').read_text(
        encoding='utf-8')
    assert "REPORT_RENDERER.pdf_bytes" not in src, \
        'rich.pdf 又走回自己那份手写实现了'
    assert 'pdf_bytes' not in (Path(__file__).resolve().parent.parent / 'app' /
                               'core' / 'report_renderer.py').read_text(encoding='utf-8'), \
        'report_renderer 里那份手写 PDF 还在——它就是丢汉字的那个'


# ---------- 报告结构：每节都在，缺做的明说 ----------

def test_all_report_sections_are_present_even_when_nothing_happened():
    """干跑时报告原本从「## 3.」直接跳到「## 6.」。

    节是条件渲染而编号写死 1–6，于是干跑（不下发、不自愈）就少两节——
    读者看到空档，分不清是这步没做还是**报告丢了内容**。
    合规报告尤其不能有这种歧义：空档会被读成「出问题了」。
    """
    from app.core.report import REPORTER
    from app.schemas import Execution

    md = REPORTER.markdown(Execution(execution_id='e-1', status='success'))
    heads = [l for l in md.splitlines() if l.startswith('## ')]
    assert len(heads) == 6, f'只有 {len(heads)} 节: {heads}'
    assert [h.split('.')[0] for h in heads] == ['## 1', '## 2', '## 3',
                                                  '## 4', '## 5', '## 6'], \
        f'节编号不连续: {heads}'


def test_absent_sections_say_why_they_are_empty():
    from app.core.report import REPORTER
    from app.schemas import Execution

    md = REPORTER.markdown(Execution(execution_id='e-1', status='success'))
    assert '未下发到设备' in md
    assert '未触发自愈' in md
    assert '未产出策略集' in md
    assert '未做校验' in md
    # 不得出现「只有标题、下面什么都没有」的节
    body = md.split('## 4.')[1].split('## 5.')[0]
    assert [l for l in body.splitlines() if l.strip()], '第 4 节是空的'


def test_sections_keep_real_content_when_data_exists():
    """「缺做的明说」不能变成「有数据也说明说没做」。"""
    from app.core.report import REPORTER
    from app.schemas import CommandResult, DeployResult, Execution

    ex = Execution(execution_id='e-2', status='success')
    ex.deploy = DeployResult(execution_id='e-2', success=True, rolled_back=False,
                             executed=[CommandResult(command='tc qdisc del dev eth0 root',
                                                    success=True, output='')],
                             mode='dry-run')
    md = REPORTER.markdown(ex)
    assert '未下发到设备' not in md, '明明有 deploy 记录却说没下发'
    assert '成功：True' in md
    assert 'tc qdisc del dev eth0 root' in md
