#!/usr/bin/env python3
"""去 AI 味密度门 —— CONTRIBUTING 规则 5（营销面可核查律）的可执行实现。

设计依据（承 protocol.md）：
  · 按**密度**检测，不按单词检测——单词出现不构成 AI 味，高频聚集才是
  · 判据是「是否具体到对方能核查」，不是「读起来像不像 AI 写的」
  · 圆整数（75% / 50%）是虚构统计的典型信号，额外标黄

退出码 0 = 通过；1 = 有阻断项。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 客户可见面：这些文件的主张会被人读到
CUSTOMER_FACING = [
    'README.md',
    'docs/ARCHITECTURE.md',
    'docs/API.md',
    'SECURITY.md',
    'CHANGELOG.md',
    'docs/closed-loop-run-report.md',
]

# 空洞套话：命中即红（承律 1「挂不上可复现物就删」）
SLOP_WORDS = [
    # 英文
    r'seamless(?:ly)?', r'\bpowerful\b', r'\brobust\b', r'cutting[- ]edge',
    r'\bdelve\b', r'\btapestry\b', r'\blandscape of\b', r'\brealm of\b',
    r'\bleverage\b', r'\bmultifaceted\b', r'\brevolutionar\w*', r'\bunleash\b',
    r'\bempower\b', r'\belevate\b', r'\bgame[- ]chang\w*', r'holistic',
    r'\bsynergy\b', r'\bholster\b', r'\btransformative\b', r'\bnext[- ]gen',
    r'\bstate[- ]of[- ]the[- ]art\b', r'blazing(?:ly)?\s*fast',
    # 中文
    r'赋能', r'一站式', r'无缝', r'极致', r'革命性', r'全方位', r'深度赋能',
    r'全新升级', r'强大的?生态', r'打造闭环',
]
SLOP_RE = re.compile('|'.join(SLOP_WORDS), re.IGNORECASE)

# 元评论 / 口水开场白
META_RE = re.compile(
    r'本文将|让我们|接下来我们来|在本文中|首先我们需要了解|'
    r'In this (?:article|guide|post)|Let\'?s (?:dive|explore|get started)|'
    r'预计阅读时间|reading time|as an AI', re.IGNORECASE)

# 装饰性 emoji：白名单只留功能性符号
# ✅ ⚠️ ❌ 属于语义状态记号（诚实表的 Real / Simulated / Not implemented 三态），
# 与 🚀✨ 这类装饰性 emoji 不同类，故列白名单。加白名单前先问：它承载语义还是纯装饰？
FUNCTIONAL = set('→←↓↑✅⚠️❌✓✗')
EMOJI_RE = re.compile(
    '[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F02F'
    '\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE0F]')

# 过渡词（按每千字密度判定，单次不算）
TRANSITION_RE = re.compile(
    r'\b(?:Moreover|Furthermore|Additionally|Nevertheless|In conclusion|'
    r'Overall|In summary)\b|此外|另外值得注意的是|总而言之', re.IGNORECASE)

# 数字：需挂来源
# 单位用 (?!\w) 收尾而不是 \b：% × 倍 等不是单词字符，其后跟标点时 \b 不成立，
# 会导致「75%」整类百分比漏检（此前只靠同行的 3x 侥幸命中过一条）。
NUM_RE = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:%|x|×|倍|ms|秒|分钟|小时|人日|人天)(?!\w)'
    r'|\b\d+(?:\.\d+)?\s*s\b'
    r'|\$\s?\d[\d,]*(?:\.\d+)?[kKmM]?(?!\w)'
    r'|\b\d[\d,]{2,}\b')
ROUND_RE = re.compile(r'\b(?:\d+0|\d+5)(?:\.\d+)?\s*(?:%|x|×|倍)(?!\w)')
# 先剥掉「本身即来源」的形态：ISO 日期、版本号、commit SHA、端口号
NOT_A_CLAIM_RE = re.compile(
    r'\b\d{4}-\d{2}-\d{2}\b'                 # ISO 日期
    r'|\bv?\d+\.\d+(?:\.\d+)?\b'             # 版本号
    r'|\b[0-9a-f]{7,40}\b'                    # commit SHA
    r'|\b\d{4,5}\b(?=\s*$)'                   # 行尾裸长整数（多为年份/端口）
)
# 来源证据：markdown 链接、行内代码、路径、commit、命令
EVIDENCE_RE = re.compile(
    r'\[[^\]]+\]\([^)]+\)|`[^`]+`|https?://|\b[0-9a-f]{7,40}\b|\.py\b|\.mjs\b|\.md\b|\.ya?ml\b|\btests?/')


def strip_fences(text: str) -> str:
    return re.sub(r'```.*?```', '', text, flags=re.S)


def check_file(path: Path) -> list[tuple[str, int, str]]:
    raw = path.read_text(encoding='utf-8')
    lines = raw.splitlines()
    # CHANGELOG 的条目列表是该格式的正当形态，不适用「连续 bullet > 7」
    bullet_check = path.name != 'CHANGELOG.md'
    findings = []

    body = strip_fences(raw)
    # 表格是一个整体：来源写在表前后的引出句/脚注即可，不要求逐行挂。
    # 逐行要求会让表格被迫塞满引用，反而逼人把表格拆成散文。
    # 判定方式：行属于某张表时，在该表起始行前 3 行与结束行后 3 行内找证据。
    # 围栏代码块内的数字是工具输出原文，不是对外主张（那正是被引用的原始证据本身），
    # 不该要求它再挂一次来源
    fenced = set()
    in_fence = False
    for idx, l in enumerate(lines):
        if l.lstrip().startswith('```'):
            in_fence = not in_fence
            fenced.add(idx)
            continue
        if in_fence:
            fenced.add(idx)

    table_spans = []          # [(first_line_idx, last_line_idx)]
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith('|'):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith('|'):
                j += 1
            table_spans.append((i, j - 1))
            i = j
        else:
            i += 1

    def table_evidence(idx: int) -> bool:
        for (a, b) in table_spans:
            if a <= idx <= b:
                ctx = lines[max(0, a - 3):a] + lines[b + 1:b + 4]
                return any(EVIDENCE_RE.search(c) for c in ctx)
        return False

    for idx, line in enumerate(lines):
        lineno = idx + 1
        if line.lstrip().startswith('|') and set(line.strip()) <= set('|-: '):
            continue                                   # 表格分隔行

        for m in SLOP_RE.finditer(line):
            findings.append(('SLOP', lineno, f'空洞套话「{m.group(0)}」需挂可复现物或删除'))
        for m in META_RE.finditer(line):
            findings.append(('META', lineno, f'元评论「{m.group(0)}」应删'))
        for ch in EMOJI_RE.findall(line):
            if ch not in FUNCTIONAL:
                findings.append(('EMOJI', lineno, f'装饰性 emoji「{ch}」应删'))

        scrubbed = NOT_A_CLAIM_RE.sub(' ', line)
        # 换行句允许证据落在紧邻的前后行——中文长句常在行中换行
        prev = lines[idx - 1] if idx > 0 else ''
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ''
        in_fence = idx in fenced
        if (NUM_RE.search(scrubbed) and not in_fence
                and not EVIDENCE_RE.search(line)
                and not EVIDENCE_RE.search(prev) and not EVIDENCE_RE.search(nxt)
                and not table_evidence(idx)):
            m = NUM_RE.search(scrubbed)
            findings.append(('NUM', lineno, f'无源数字「{m.group(0).strip()}」需挂命令/报告/链接'))
        # 圆整数字是「值得复核的信号」而非判决：实测值恰好是整数很常见
        # （0% / 10% 丢包就是 netem 参数本身）。已挂来源就不再提示。
        elif (ROUND_RE.search(scrubbed) and not in_fence
              and not EVIDENCE_RE.search(line)
              and not EVIDENCE_RE.search(prev) and not EVIDENCE_RE.search(nxt)):
            m = ROUND_RE.search(scrubbed)
            findings.append(('ROUND', lineno, f'圆整统计「{m.group(0).strip()}」需换实测值'))

    words = max(1, len(body) // 2)
    trans = len(TRANSITION_RE.findall(body))
    if trans / words * 1000 > 1:
        findings.append(('TRANS', 0, f'过渡词密度 {trans / words * 1000:.1f}/千字 > 1，机械连接感'))

    if bullet_check:
        run = best = 0
        for l in lines:
            run = run + 1 if l.strip().startswith(('- ', '* ')) else 0
            best = max(best, run)
        if best > 7:
            findings.append(('BULLET', 0, f'连续项目符号 {best} 条 > 7，改为段落或表格'))

    bbest = max((len(re.findall(r'\*\*[^*]+\*\*', l)) for l in lines), default=0)
    if bbest > 4:
        findings.append(('BOLD', 0, f'单行加粗 {bbest} 处 > 4，加粗轰炸'))

    return findings


def main() -> int:
    targets = [ROOT / f for f in CUSTOMER_FACING if (ROOT / f).exists()]
    if not targets:
        print('  客户可见文件一个都没找到——检查 CUSTOMER_FACING 配置')
        return 1
    total = 0
    for p in targets:
        findings = check_file(p)
        rel = p.relative_to(ROOT)
        if findings:
            print(f'  ✗ {rel}')
            for kind, line, msg in findings:
                loc = f':{line}' if line else ''
                print(f'      [{kind}]{loc} {msg}')
            total += len(findings)
        else:
            print(f'  ✓ {rel}')
    print(f'\n  客户可见面 AI 味命中 {total} 项')
    return 1 if total else 0


if __name__ == '__main__':
    raise SystemExit(main())
