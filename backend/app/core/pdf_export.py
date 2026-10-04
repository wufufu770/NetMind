"""PDF 导出。

此前两条 PDF 路径（`report_pdf` 与 `REPORT_RENDERER.pdf_bytes`）各自手写了一份
最小 PDF，用 `latin-1` + `ignore` 编码。三个问题，都实测确认过：

  1. **中文被静默丢弃**。报告正文是中文，而 base-14 的 Helvetica 只能表示
     Latin-1，于是 `encode('latin-1', 'ignore')` 把每一个汉字都扔掉。用
     `pdftotext` 读生成的文件，拿到的是：
         # NetMind exec-…- Status.success## 1.  - video_meeting
     而 markdown 原文是：
         ## 1. 意图摘要 / - 描述：给会议网提高优先级
     **用户导出 PDF 得到一份几乎没有内容的文档，且没有任何报错。**
  2. **xref 表是假的**：`startxref 0` 指向文件开头而不是 xref 实际位置，
     偏移全为 0。宽容的阅读器能靠扫描 `N M obj` 重建，严格校验器会拒绝。
  3. `/Length` 是猜的。

现在用 reportlab 生成真正的 PDF，并解决字体问题——Helvetica 没有汉字，
必须换一款含 CJK 字形的字体。字体从系统里找，找不到就**明确报错**，而不是
退回到那份被阉割的输出。
"""
from __future__ import annotations

import io
import os
from pathlib import Path

# 已知的 CJK 字体候选路径（按偏好排序）。覆盖 Debian/Ubuntu、Alpine、
# 常见桌面发行版与 Noto/arphic 两个主要来源。
CJK_FONT_CANDIDATES = (
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/arphic/uming.ttc',
    '/usr/share/fonts/truetype/arphic/ukai.ttc',
    '/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/System/Library/Fonts/PingFang.ttc',
    'C:/Windows/Fonts/msyh.ttc',
)
# reportlab 接受的是**注册过的字体名**，不是路径；且 .ttc 是字体集合，
# 必须给 subfontIndex 指出用哪一款。直接 `setFont('/path/to.ttc')` 会 KeyError。
_REGISTERED: str | None = None


def register_cjk_font() -> str | None:
    """把系统 CJK 字体注册进 reportlab，返回可用的字体名（失败为 None）。"""
    global _REGISTERED
    if _REGISTERED is not None:
        return _REGISTERED
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in candidate_fonts():
        for idx in (0, 1, 2):
            for name in ('NetMindCJK', f'NetMindCJK_{idx}'):
                try:
                    pdfmetrics.registerFont(TTFont(name, path, subfontIndex=idx))
                    _REGISTERED = name
                    return name
                except Exception:
                    continue
    return None
# 显式覆盖：NETMIND_PDF_FONT=/path/to/font.ttc
FONT_ENV = 'NETMIND_PDF_FONT'


class PdfFontUnavailable(RuntimeError):
    """找不到能表示中文的字体。**不退回被静默阉割的输出。**"""


def candidate_fonts() -> list[str]:
    """按偏好顺序列出**存在的**候选字体路径。

    要注意 reportlab 只支持 TrueType（glyf）轮廓：Noto CJK 的 .ttc 是 CFF/OTF，
    reportlab 装不上。所以「文件存在」不等于「能用」，得逐个试到能注册的为止。
    """
    out: list[str] = []
    override = os.getenv(FONT_ENV, '').strip()
    if override:
        return [override] if Path(override).exists() else []
    for p in CJK_FONT_CANDIDATES:
        if Path(p).exists():
            out.append(p)
    return out


def find_cjk_font() -> str | None:
    """第一个**能被 reportlab 注册**的 CJK 字体；一个都没有则为 None。"""
    for path in candidate_fonts():
        for idx in (0, 1, 2):
            try:
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                pdfmetrics.registerFont(TTFont(f'_probe_{idx}_{len(path)}', path,
                                               subfontIndex=idx))
                return path
            except Exception:
                continue
    return None


def has_cjk(text: str) -> bool:
    return any('⺀' <= ch <= '鿿' or '＀' <= ch <= '￯' for ch in text)


def markdown_to_pdf(markdown: str, *, title: str = 'NetMind Report',
                     max_chars: int = 12000) -> bytes:
    """markdown → PDF 字节。缺 CJK 字体时抛 PdfFontUnavailable，不产出残缺文件。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    text = (markdown or '')[:max_chars]
    if has_cjk(text):
        font = register_cjk_font()
        if not font:
            raise PdfFontUnavailable(
                '报告含中文，但系统里找不到可用的 CJK 字体，导出会丢失全部汉字。'
                f'装一款中文字体，或用 {FONT_ENV}=/path/to/font.ttc 指定路径；'
                '也可以改用 .md / .html 导出——那两条不做字符集裁剪，内容完整。')
    else:
        # 纯 ASCII/Latin 内容用内置字体即可，不要求系统装有 CJK 字体
        font = None

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    margin = 18 * mm
    c.setTitle(title)

    y = height - margin
    line_h = 5.2 * mm
    draw_width = width - 2 * margin

    # stringWidth 的签名是 (text, fontName, fontSize)——字体名不能漏，
    # 漏了会把字号当字体名传进去（KeyError: '9'）。
    face = font or 'Helvetica'
    for raw in text.splitlines():
        # 先量后画：放不下就断到下一行，而不是画出页面外
        line = raw
        while line:
            c.setFont(face, 9)
            probe = line
            while probe and c.stringWidth(probe, face, 9) > draw_width:
                probe = probe[:-1]
            if not probe:
                break
            if y < margin:
                c.showPage()
                y = height - margin
            c.drawString(margin, y, probe)
            y -= line_h
            line = line[len(probe):]
    c.save()
    return buf.getvalue()
