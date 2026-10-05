#!/usr/bin/env python3
"""门禁定义与执行器。

每条门禁声明失败时走哪条退路：block / autofix / rollback / warn。
退路优先级 block > rollback > autofix > warn。

选 autofix 的门槛是这个修复不涉及判断——只要需要理解语义才能决定怎么修，
就必须 block。这是协议里的硬约束，不是建议。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOP_DIR = ROOT / '.netmind-loop'

# ---------------------------------------------------------------- 门禁定义


@dataclass
class Gate:
    id: str
    desc: str
    on_fail: str                       # block | autofix | rollback | warn
    check: str | None = None           # 内联 Python 检查代码，失败抛 AssertionError/异常
    cmd: list[str] | None = None       # 外部命令 argv
    max_attries: int = 1
    fix: str | None = None             # autofix 动作 id
    fix_desc: str = ''


# 内联检查代码片段统一拿到的命名空间
NS = {'ROOT': ROOT, 're': re, 'json': json, 'subprocess': subprocess}


def _split_params(text):
    """按顶层逗号切参数列表。括号/花括号/方括号内的逗号不算分隔符。

    必须这样做：`summaryCell(value, { yes, no, unknown = '未知' } = {})` 里
    花括号内也有逗号，朴素 split 会把它切成三段，算出错误的必填参数个数，
    门禁就开始在合法代码上报错——**出误报的门禁比没有门禁更糟**，它会被人关掉。
    """
    out, buf, depth = [], [], 0
    for ch in text:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = ''.join(buf).strip()
    if tail:
        out.append(tail)
    return [a for a in out if a]


GATES: list[Gate] = [
    Gate(
        id='readonly-cannot-write-anything',
        desc='只读凭据必须对**每一个**写方法端点返回 403（全站枚举，不抽样）',
        on_fail='block',
        check=r"""
# 只读凭据此前只被手工试过几个端点，从来没有全站枚举过。
# 而「某个新加的端点忘了接只读校验」正是这个项目反复吃亏的形态：
# 测试测的是被挑中的那条路径，没被挑中的那些没人知道。
#
# 现在全站枚举：OpenAPI 里每一个 post/put/patch/delete，都必须对只读凭据
# 返回 403。实测 70 个端点全部符合——但**当时没有任何东西在保证它继续符合**。
#
# 顺带钉住反面：只对**只读**凭据要求 403。管理员凭据必须仍能通过，
# 否则一个「全都拦住」的退化实现也能让这条门禁变绿。
import os as _os
import sys as _sys
_sys.path.insert(0, str(ROOT / 'backend'))
_k = ('NETMIND_ADMIN_TOKEN', 'NETMIND_READONLY_TOKEN', 'NETMIND_ALLOW_ANON_READONLY',
      'NETMIND_TRUST_PROXY', 'NETMIND_RATE_LIMIT')
_s = {_k2: _os.environ.get(_k2) for _k2 in _k}
try:
    _os.environ['NETMIND_ADMIN_TOKEN'] = 'gate-adm'
    _os.environ['NETMIND_READONLY_TOKEN'] = 'gate-ro'
    # 限流走在鉴权之前（挡住未授权洪水是有意的），开着会盖住鉴权结论
    _os.environ['NETMIND_RATE_LIMIT'] = 'off'
    _os.environ.pop('NETMIND_ALLOW_ANON_READONLY', None)
    _os.environ.pop('NETMIND_TRUST_PROXY', None)

    import app.core.access as _access
    _access._client_host = lambda request: '203.0.113.9'      # 远程视角
    from fastapi.testclient import TestClient               # noqa: E402
    from app.main import app as fastapi_app                 # noqa: E402

    _spec = fastapi_app.openapi()
    _mut = sorted({(m.upper(), path) for path, ops in _spec['paths'].items()
                   for m in ops if m in ('post', 'put', 'patch', 'delete')})
    assert len(_mut) >= 40, f'只枚举到 {len(_mut)} 个写方法端点——端点表可能解析错了'

    # 反面检查会用**管理员凭据真跑**全部 70 个端点，而其中
    # config/reset-runtime、config/import、audit/run、tools/call 等**会真改 store**。
    # 只读那一半是 403、不会改动，所以第一次没被污染门禁抓到；真跑管理员那半才暴露。
    from app.store import STORE as _S          # noqa: E402
    _snap = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
             for k, v in (('executions', _S.executions), ('telemetry', _S.telemetry),
                           ('approvals', _S.approvals), ('rules', _S.rules),
                           ('models', _S.models), ('agents', _S.agents),
                           ('tools', _S.tools), ('workflows', _S.workflows),
                           ('mcp_servers', _S.mcp_servers), ('templates', _S.templates),
                           ('templates_mgmt', getattr(_S, 'templates_mgmt', None)))}

    def _restore() -> None:
        _S.executions.clear();  _S.executions.update(_snap['executions'])
        _S.telemetry.clear();   _S.telemetry.extend(_snap['telemetry'])
        _S.approvals.clear();   _S.approvals.update(_snap['approvals'])
        _S.rules.clear();       _S.rules.update(_snap['rules'])
        _S.models.clear();      _S.models.update(_snap['models'])
        _S.agents.clear();      _S.agents.update(_snap['agents'])
        _S.tools.clear();       _S.tools.update(_snap['tools'])
        _S.workflows.clear();   _S.workflows.update(_snap['workflows'])
        _S.mcp_servers.clear(); _S.mcp_servers.update(_snap['mcp_servers'])
        _S.templates.clear();   _S.templates.update(_snap['templates'])

    try:
      with TestClient(fastapi_app) as _c:
        _leaks, _odd = [], []
        for _m, _p in _mut:
            _r = _c.request(_m, _p, headers={'Authorization': 'Bearer gate-ro'}, json={})
            if _r.status_code != 403:
                (_leaks if _r.status_code < 300 else _odd).append((_m, _p, _r.status_code))
        assert not _leaks, (
            '只读凭据在这些写端点上没有被拦住（会真的改动状态）:\n    '
            + '\n    '.join(f'{m} {p} → {s}' for m, p, s in _leaks))
        assert not _odd, (
            '只读凭据在这些写端点上返回的不是 403（多半是 404/405，说明鉴权没先于路由生效）:\n    '
            + '\n    '.join(f'{m} {p} → {s}' for m, p, s in _odd))

        # 反面：管理员凭据必须仍能通过，否则「全都拦住」也能让这条门禁变绿
        _adm_ok = 0
        for _m, _p in _mut:
            _r = _c.request(_m, _p, headers={'Authorization': 'Bearer gate-adm'}, json={})
            if _r.status_code != 403:
                _adm_ok += 1
        assert _adm_ok >= len(_mut) - 5, (
            f'管理员凭据只有 {_adm_ok}/{len(_mut)} 个端点没被 403 拦住——'
            f'鉴权可能退化成了「谁都拒绝」')
    finally:
        _restore()
finally:
    for _k2, _v in _s.items():
        if _v is None:
            _os.environ.pop(_k2, None)
        else:
            _os.environ[_k2] = _v
""",
    ),
    Gate(
        id='diagnose-live-actually-tries',
        desc='diagnose --live 必须真的用配置的端口去连，并如实区分「没请求」与「请求了没成功」',
        on_fail='block',
        check=r"""
# 两个问题，都在实验台设备上实测确认过：
#
# ① **端口从不透传** —— `_collect_live` 有 `ssh_port: int = 22` 形参，而
#    `diagnose()` 从不传它。无论 NETMIND_SSH_PORT 设成什么，采集都打 22 端口。
#    实测：设备映射到 2222，采集前一律 `[]`（全部超时），修后采到 `['r2']`。
#    **diagnose --live 对任何非 22 端口的设备完全不可用。**
#
# ② **「没请求」与「请求了但失败」混为一谈** —— 采集全失败时 findings 一律写
#    "no device access requested"，而实况是访问请求过了、失败了。使用者会去
#    查参数而不是查连接；逐节点的失败原因也被丢掉，只剩一句笼统的 notes。
import sys as _sys
_sys.path.insert(0, str(ROOT / 'backend'))
import inspect as _insp
try:
    from app.diagnose import engine as E
    from app.diagnose import checks as C

    # ① 端口可传、且不传时读 env
    assert 'ssh_port' in _insp.signature(E.diagnose).parameters, \
        'diagnose() 没有 ssh_port 形参'
    _src = _insp.getsource(E.diagnose)
    assert 'NETMIND_SSH_PORT' in _src, \
        '设了 NETMIND_SSH_PORT 却没读——设了不用是最坑的形态'
    assert 'ssh_port=' in _src, '端口拿到了却没传给 _collect_live'

    # ② 逐节点原因必须留进 notes
    _orig = E._collect_live
    E._collect_live = lambda p, h, u, pw, ssh_port=22: (None, ['r1: 超时', 'r2: 认证失败'])
    try:
        _r = E.diagnose('examples/clab-broken.yml', live=True,
                        host_map={'r1': '1.1.1.1'}, ssh_user='u', ssh_password='p')
    finally:
        E._collect_live = _orig
    _notes = ' '.join(_r.get('notes') or [])
    assert 'r1' in _notes and '超时' in _notes, f'逐节点失败原因被丢掉: {_r.get("notes")}'

    # ③ 措辞不得把「请求过」写成「没请求」
    _skip = next((f for f in _r['findings'] if f['id'] == 'collection-skipped'), None)
    assert _skip is not None, '没有 collection-skipped 这条 finding'
    assert 'no device access requested' not in _skip['title'], (
        f'明明请求过却说没请求: {_skip["title"]}')
finally:
    pass
""",
    ),
    Gate(
        id='audit-unchecked-is-not-passed',
        desc='巡检读不到数据时必须报 unknown —— 安全审计不得在没检查过的设备上判通过',
        on_fail='block',
        check=r"""
# 巡检项是 **OpenWrt 专用**的（uci / ubus / dropbear 都是 OpenWrt 的东西），
# 此前却对着任何设备跑。实测一台 Alpine 容器：uci / nft / ubus 全都不存在，
# shell 回一行 `-bash: uci: command not found`，而解析器把**这行错误文本当成了
# 设置值** —— `PasswordAuth` 不在 {on,1} 里，于是判成 ok。
#
# 结果：一台从未被真正检查过的设备，六项里四项报「通过」。**这是安全工具
# 最危险的失败模式**——使用者据此以为设备是安全的。
import sys as _sys
_sys.path.insert(0, str(ROOT / 'backend'))
try:
    from app.core import audit as A

    ALPINE = {
        'ubus call system board': '-bash: ubus: command not found',
        'cat /etc/openwrt_release': '-bash: cat: /etc/openwrt_release: No such file or directory',
        'uname -a': 'Linux client2 5.15.167 x86_64 GNU/Linux',
        'uci -q get dropbear.@dropbear[0].PasswordAuth': '-bash: uci: command not found',
        'uci -q get upnpd.config.enabled': '-bash: uci: command not found',
        'nft list ruleset | head -40': '-bash: nft: command not found',
        'iptables -L -n | head -40': '-bash: iptables: command not found',
        'ss -tln': 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*',
        'netstat -tln': '-bash: netstat: command not found',
        'uci -q show wireless': '-bash: uci: command not found',
    }
    OPENWRT = {
        'ubus call system board': '{"release":{"distribution":"OpenWrt","version":"23.05.5"}}',
        'cat /etc/openwrt_release': "DISTRIB_RELEASE='23.05.5'",
        'uname -a': 'Linux HomeGW 5.15.167 aarch64',
        'uci -q get dropbear.@dropbear[0].PasswordAuth': 'on',
        'uci -q get upnpd.config.enabled': '0',
        'nft list ruleset | head -40': 'chain input {\ntype filter hook input; policy drop;\n}',
        'ss -tln': 'tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*',
        'uci -q show wireless': "wireless.default_radio0.encryption='psk2'",
    }

    _by = {}
    for _c in A.CHECKS:
        _by[_c['id']] = _c['eval']

    # ① 读不到就是 unknown，不是 ok
    for _cid in ('ssh_password_auth', 'upnp', 'wireless_encryption', 'firewall_rules'):
        _r = _by[_cid](ALPINE)
        assert _r['status'] == 'unknown', \
            f'{_cid} 在读不到数据时判成 {_r["status"]}——shell 报错被当成了实测值'
        assert '未检查' in _r['evidence'], _r['evidence']
        assert 'PasswordAuth=-bash' not in _r['evidence'], '报错文本仍被当成配置值展示'

    # ② 真设备仍要给真判断——不能因为修了「读不到」就一片 unknown
    assert _by['ssh_password_auth'](OPENWRT)['status'] == 'warn', 'OpenWrt 口令开着应报 warn'
    assert _by['upnp'](OPENWRT)['status'] == 'ok'
    assert '23.05.5' in _by['firmware'](OPENWRT)['evidence']

    # ③ 结论层：有项目没检查就不能说「基线通过」
    _results = [c['eval'](ALPINE) for c in A.CHECKS]
    _counts = {st: sum(1 for x in _results if x['status'] == st)
               for st in ('ok', 'warn', 'fail', 'unknown', 'error', 'info')}
    _unchecked = _counts['unknown'] + _counts['error']
    assert _unchecked >= 4, f'Alpine 上只有 {_unchecked} 项无法检查，判定逻辑可能被改弱'
finally:
    pass
""",
    ),
    Gate(
        id='rich-html-has-no-empty-headings',
        desc='rich.html 不得渲染出空标题；标题层级要保留',
        on_fail='block',
        check=r"""
# 第一版是一行三元表达式：
#   f'<p>…</p>' if line and not line.startswith('#') else f'<h2>…</h2>'
# 两个问题都实测过：
#   ① **空行也落进 else 分支** —— markdown 每节之间都有空行，于是每个空行
#      渲染成一个空的 `<h2></h2>`，看起来像报告缺内容
#   ② `#` 与 `##` 全被拍平成 `<h2>`，标题层级丢失
import sys as _sys
_sys.path.insert(0, str(ROOT / 'backend'))
try:
    from app.core.report_renderer import REPORT_RENDERER
    from app.schemas import Execution

    _html = REPORT_RENDERER.html(Execution(execution_id='e-1', status='success'))
    for _bad in ('<h1></h1>', '<h2></h2>', '<h3></h3>', '<p></p>'):
        assert _bad not in _html, f'renderer 产出了空节点 {_bad}'
    assert '<h1>' in _html, '文档标题没有用 h1'
    for _n in range(1, 7):
        assert f'<h2>{_n}.' in _html, f'缺第 {_n} 节的 h2 标题'
    assert '<meta charset="utf-8">' in _html
    # 内容里的尖括号必须转义，否则执行 id 之类的字段能破坏页面结构
    _h2 = REPORT_RENDERER.html(Execution(execution_id='e-<script>', status='success'))
    assert '<script>' not in _h2, '执行 id 里的尖括号没转义'
    assert '&lt;script&gt;' in _h2
finally:
    pass
""",
    ),
    Gate(
        id='report-keeps-every-section',
        desc='报告六节恒在；条件渲染的节缺做时必须明说，不得留下编号空档',
        on_fail='block',
        check=r"""
# 合规报告里，节编号的连续性是承诺的一部分。此前第 2–5 节是条件渲染而编号
# 写死 1–6，于是干跑（不下发、不自愈）时报告变成：
#     ## 1. 意图摘要 / ## 2. 策略集 / ## 3. 验证结果 / ## 6. Agent 执行链路
# 读者看到空档，**分不清是这步没做还是报告丢了内容**——而合规场景里
# 两者都会被读成「出问题了」。空节必须明说为什么空。
import sys as _sys
_sys.path.insert(0, str(ROOT / 'backend'))
try:
    from app.core.report import REPORTER
    from app.schemas import CommandResult, DeployResult, Execution

    _md = REPORTER.markdown(Execution(execution_id='e-1', status='success'))
    _heads = [l for l in _md.splitlines() if l.startswith('## ')]
    assert len(_heads) == 6, f'只有 {len(_heads)} 节，编号有空档: {_heads}'
    for _n in ('1', '2', '3', '4', '5', '6'):
        assert any(h.startswith(f'## {_n}.') for h in _heads), f'缺第 {_n} 节'
    for _why in ('未下发到设备', '未触发自愈', '未产出策略集', '未做校验'):
        assert _why in _md, f'空节没有说明为什么（{_why}）——编号在但内容空着等于没写'

    # 有数据时不得还说「没做」
    _ex = Execution(execution_id='e-2', status='success')
    _ex.deploy = DeployResult(execution_id='e-2', success=True, rolled_back=False,
                              executed=[CommandResult(command='tc qdisc del dev eth0 root',
                                                      success=True, output='')],
                              mode='dry-run')
    _md2 = REPORTER.markdown(_ex)
    assert '未下发到设备' not in _md2, '明明有 deploy 记录，报告却说没下发'
    assert 'tc qdisc del dev eth0 root' in _md2, '真实执行命令没进报告'
finally:
    pass
""",
    ),
    Gate(
        id='pdf-export-does-not-drop-chinese',
        desc='PDF 导出不得静默丢弃汉字；缺中文字体时必须明确报错而不是返回残缺文件',
        on_fail='block',
        check=r"""
# 报告正文是中文，而 base-14 的 Helvetica 只能表示 Latin-1。此前两条 PDF 路径
# 各自手写了一份最小 PDF，用 `encode('latin-1', 'ignore')` 编码，于是
# **每一个汉字都被静默丢弃**。用 pdftotext 读生成的文件：
#     # NetMind exec-…- Status.success## 1.  - video_meeting
# 而 markdown 原文：
#     ## 1. 意图摘要 / - 描述：给会议网提高优先级
# **用户导出 PDF 得到一份几乎没有内容的文档，且没有任何报错。**
import os as _os
import subprocess as _sp
import sys as _sys
# 只在单条内层脚本里改 path —— 污染外层 exec 命名空间会影响其他门禁
_sys.path.insert(0, str(ROOT / 'backend'))      # 只在单条内层脚本里改 path，污染外层 exec 命名空间
_k = ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_RATE_LIMIT')
_s = {_k2: _os.environ.get(_k2) for _k2 in _k}
try:
    for _k2 in _k:
        _os.environ.pop(_k2, None)
    import app.core.access as _access
    _access._client_host = lambda request: '127.0.0.1'
    from fastapi.testclient import TestClient          # noqa: E402
    from app.main import app as fastapi_app            # noqa: E402
    from app.core.pdf_export import PdfFontUnavailable, markdown_to_pdf  # noqa: E402

    _md = '# NetMind 执行报告：exec-1' + chr(10) + '- 描述：给会议网提高优先级' + chr(10)
    _pdf = markdown_to_pdf(_md)
    assert _pdf[:5] == b'%PDF-', 'PDF 头不对'
    assert len(_pdf) > 5000, f'PDF 只有 {len(_pdf)} 字节，疑似汉字被丢掉只剩骨架'

    # 用真实解析器把文字取回来核对
    import re, tempfile
    _txt = ''
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as _f:
        _f.write(_pdf); _p = _f.name
    try:
        _r = _sp.run(['pdftotext', _p, '-'], capture_output=True, text=True, timeout=60)
        _txt = _r.stdout if _r.returncode == 0 else ''
    except (FileNotFoundError, _sp.TimeoutExpired):
        _txt = ''
    finally:
        _os.unlink(_p)
    if _txt:
        for _tok in ('执行报告', '描述', '给会议网提高优先级'):
            assert _tok in _txt, f'PDF 里读不回「{_tok}」——汉字被丢了。实际：{_txt[:200]}'

    # 端点层：缺字体时必须是 422 + 修法，不能是 200 + 残缺文件。
    # **要造执行记录就得还原**——本门禁第一版就是漏了这里，
    # 被 gates-do-not-pollute-each-other 当场抓到（它污染了 STORE.executions）。
    from app.store import STORE as _S
    _saved_exec = dict(_S.executions)
    _saved_tel = list(_S.telemetry)
    _saved_appr = dict(_S.approvals)
    try:
        with TestClient(fastapi_app) as _c:
            _eid = _c.post('/api/intent/submit',
                           json={'text': '给会议网提高优先级', 'dry_run': True}).json()['execution_id']
            _resp = _c.get(f'/api/report/{_eid}.pdf')
            assert _resp.status_code == 200, f'正常路径返回 {_resp.status_code}'
    finally:
        _S.executions.clear(); _S.executions.update(_saved_exec)
        _S.telemetry.clear(); _S.telemetry.extend(_saved_tel)
        _S.approvals.clear(); _S.approvals.update(_saved_appr)

    import app.core.pdf_export as _pe
    _orig = _pe.register_cjk_font
    _pe.register_cjk_font = lambda: None
    try:
        _raised = False
        try:
            markdown_to_pdf(_md)
        except PdfFontUnavailable:
            _raised = True
        assert _raised, '缺中文字体时不报错——又回到「产出残缺文件还不吭声」'
    finally:
        _pe.register_cjk_font = _orig
finally:
    for _k2, _v in _s.items():
        if _v is None:
            _os.environ.pop(_k2, None)
        else:
            _os.environ[_k2] = _v
""",
    ),
    Gate(
        id='honesty-table-signals-current-state',
        desc='诚实表的 ⚠️ 只表示「今天的限制」；已修复的坑不得继续挂 ⚠️',
        on_fail='block',
        check=r"""
# 诚实表是**契约**（CONTRIBUTING 规则 1）。⚠️ 的含义必须是「这是今天的限制」。
# 把修好的坑继续留在 ⚠️ 列，是**反向误导**——读表的人据此判断能不能用，
# 而留着会让他们以为那些问题还在。
#
# 实测踩过：三条行（缺测哨兵值、诊断置信度默认、状态端点恒真）已经修完，
# 正文却仍以「⚠️ previously …」的形式挂在 ⚠️ 列里，9 条 ⚠️ 里有 3 条是历史。
from pathlib import Path as _P
_block = (_P(ROOT) / 'README.md').read_text(encoding='utf-8')
_block = _block[_block.index("## What's real"):_block.index('## Vendor support')]
_rows = [l for l in _block.splitlines() if l.startswith('|') and '---' not in l]

_stale = []
for _l in _rows:
    if '⚠️' not in _l:
        continue
    # ⚠️ 后面紧跟 previously / 曾 / 已经修 —— 说明这条是历史而不是现有限制
    for _m in re.finditer(r'⚠️\s*([^|；;]{0,20})', _l):
        _head = _m.group(1)
        if re.search(r'previously|曾|已(经)?修|原来', _head):
            _stale.append(_l.split('|')[1].strip())
            break
assert not _stale, (
    '这些行的 ⚠️ 讲的是**已修复**的历史，不是今天的限制：'
    + ', '.join(_stale)
    + '。它们该移出 ⚠️ 列（CHANGELOG 里有完整记录）。'
    + '留着会让读表的人以为问题还在——与诚实相反的方向。')

# 诚实表必须真的列出「修过的同类问题」，否则移出去的信息就丢了
assert '修过的同类问题' in _block, \
    '诚实表里应有「修过的同类问题」小节，否则把历史移出 ⚠️ 就等于丢信息'

# 至少保留若干条现有限制——全部清空通常意味着表被掏空了，而不是问题都解决了
_warned = [l for l in _rows if '⚠️' in l]
assert len(_warned) >= 3, f'只剩 {len(_warned)} 条 ⚠️，确认一下是不是把限制也一起删了'
""",
    ),
    Gate(
        id='mcp-stdio-honours-the-safety-model',
        desc='MCP stdio：tools/call 默认干跑、tools/list 只列已启用工具、协议错误用标准码',
        on_fail='block',
        check=r"""
# 走 stdio **不比走 HTTP 更可信、更不受限**。一个对外的协议入口若默认真执行，
# 等于给安全门开了个后门：认证、审批、dry_run 全绕过去了。
#
# 两条不妥协（均已用反例注入证伪）：
#   · `tools/call` 默认 dry_run=true，要真执行必须显式 dry_run=false
#   · `tools/list` 只列已启用工具——清单给了就会有人照着调
import json as _json
import subprocess as _sp
import sys as _sys
_lines = [
    "import json, sys",
    "sys.path.insert(0, 'backend')",
    "from app import mcp_server as M",
    "import app.core.mcp_protocol as mp",
    "seen = []",
    "class Fake:",
    "    def list_tools(self):",
    "        return {'tools': [{'name': 'a', 'enabled': True},",
    "                        {'name': 'b', 'enabled': False}]}",
    "    def call_tool(self, name, arguments=None, dry_run=True):",
    "        seen.append(dry_run)",
    "        return {'ok': True}",
    "f = Fake()",
    "out = {}",
    "out['tools'] = [t['name'] for t in M.handle(",
    "    {'jsonrpc':'2.0','id':1,'method':'tools/list'}, mcp=f)['result']['tools']]",
    "M.handle({'jsonrpc':'2.0','id':2,'method':'tools/call',",
    "         'params':{'name':'a','arguments':{}}}, mcp=f)",
    "out['default_dry_run'] = seen[-1]",
    "M.handle({'jsonrpc':'2.0','id':3,'method':'tools/call',",
    "         'params':{'name':'a','arguments':{},'dry_run':False}}, mcp=f)",
    "out['opt_in'] = seen[-1]",
    "out['bad_method'] = M.handle({'jsonrpc':'2.0','id':4,'method':'nope'}, mcp=f)['error']['code']",
    "out['bad_json'] = M.parse_line('{oops', mcp=f)['error']['code']",
    "out['notif'] = M.handle({'jsonrpc':'2.0','method':'ping'}, mcp=f)",
    "out['real_list_count'] = len(M._tool_entries(mp.MCP))",
    "print(json.dumps(out, ensure_ascii=False))",
]
_probe = chr(10).join(_lines)
_r = _sp.run([_sys.executable, '-c', _probe], cwd=ROOT,
             capture_output=True, text=True, timeout=180)
assert _r.returncode == 0, f'探针跑不起来: {_r.stderr[-400:]}'
_d = _json.loads(_r.stdout.strip().splitlines()[-1])

assert _d['default_dry_run'] is True, \
    f'tools/call 默认真执行了（dry_run={_d["default_dry_run"]}）——stdio 成了绕过安全门的后门'
assert _d['opt_in'] is False, '显式 dry_run=false 应当放行'
assert _d['tools'] == ['a'], f'禁用工具仍在清单里: {_d["tools"]}'
assert _d['bad_method'] == -32601, f'未知方法应回 -32601，实际 {_d["bad_method"]}'
assert _d['bad_json'] == -32700, f'坏 JSON 应回 -32700，实际 {_d["bad_json"]}'
assert _d['notif'] is None, 'notification 不该有响应'
assert _d['real_list_count'] > 0, '真实工具清单是空的——服务起来没东西可用'
""",
    ),
    Gate(
        id='cli-renders-real-fields',
        desc='CLI 表格不得整列显示 `-`——那通常是没读对字段名，不是「没有该信息」',
        on_fail='block',
        check=r"""
# `netmind vendors` 第一版把字段写成 `verification`，真实响应里是 `level`，
# 于是「验证等级」整列显示 `-`——而那一列恰恰是这张表唯一要说的事：
# 只有 verified 的那家在真机上跑通过采集。
#
# **一列全是 `-` 的表比没有这张表更糟**：它看起来像「没有等级信息」，
# 实际是「我没读对字段」。而这种错在肉眼扫一遍输出时极易滑过去。
import json
import subprocess
import sys

_lines = [
    "import json, sys",
    "sys.path.insert(0, 'backend')",
    "import app.cli as m",
    "payload = {'summary': {'verified': 1, 'declared': 1},",
    "           'vendors': [{'name': 'probe-vendor', 'kinds': ['k1'],",
    "                       'transport': 'netmiko', 'driver': 'd1',",
    "                       'level': 'verified', 'note': 'n'}]}",
    "m._get = lambda *a, **k: payload",
    "from typer.testing import CliRunner",
    "res = CliRunner().invoke(m.app, ['vendors'])",
    "print(json.dumps({'exit_code': res.exit_code, 'stdout': res.stdout}, ensure_ascii=False))",
]
_probe = chr(10).join(_lines)   # 直接用原始行：repr() 之后每行会变成裸字符串字面量，
                      # 拼起来的源码是一串什么都不做的表达式，不是原代码
_r = subprocess.run([sys.executable, '-c', _probe], cwd=ROOT,
                    capture_output=True, text=True, timeout=180)
assert _r.returncode == 0, f'探针跑不起来: {_r.stderr[-300:]}'
_d = json.loads(_r.stdout.strip().splitlines()[-1])
assert _d['exit_code'] == 0, f"netmind vendors 退出码 {_d['exit_code']}"
_row = next((l for l in _d['stdout'].splitlines() if 'probe-vendor' in l and '│' in l), '')
assert _row, '厂商表格里找不到探针厂商那一行'
_cells = [c.strip() for c in _row.split('│') if c.strip()]
_empty = [i for i, c in enumerate(_cells) if c in ('-', '—', '')]
# 首列是厂商名，末列是验证等级；中间不能出现整列空缺
assert len(_empty) <= 1, (
    f'厂商行里有多处空缺 {_empty}，单元格: {_cells}——'
    f'八成是字段名读错了。一列全是占位符的表比没有这张表更糟')
assert 'verified' in _row, f'验证等级列没显示出真实值: {_row}'
assert 'k1' in _row, f'型号（kinds）没显示: {_row}'
""",
    ),
    Gate(
        id='cli-never-silent',
        desc='CLI 不得以退出 0 + 空 stdout 结束——沉默让使用者无法区分失败与无数据',
        on_fail='block',
        check=r"""
# CLI 是一层薄适配器，但它是对用户说话的那一层。在那一层，「沉默」最贵：
# 命令退出 0、stdout 全空，使用者无法区分「命令失败了」与「确实没有数据」。
#
# 实测：`netmind logs` 在空 store 上循环一次都不执行，退出 0、零输出。
import json
import subprocess
import sys

# 注意：这里的探针用 chr(10).join 拼出来而不是 r'...'——
# 嵌套三引号会把本检查体提前闭合。
_probe = chr(10).join(['import json, sys', "sys.path.insert(0, 'backend')", 'import app.cli as m', 'm._get = lambda *a, **k: []', 'from typer.testing import CliRunner', "res = CliRunner().invoke(m.app, ['logs', '--limit', '3'])", "print(json.dumps({'exit_code': res.exit_code, 'stdout': res.stdout}, ensure_ascii=False))"])
_r = subprocess.run([sys.executable, '-c', _probe], cwd=ROOT,
                    capture_output=True, text=True, timeout=180)
assert _r.returncode == 0, f'探测脚本跑不起来: {_r.stderr[-300:]}'
_d = json.loads(_r.stdout.strip().splitlines()[-1])
assert _d['exit_code'] == 0, f'空 logs 应当正常退出，实际 {_d["exit_code"]}'
assert _d['stdout'].strip(), (
    'netmind logs 在空结果时 stdout 全空——使用者无法区分「命令失败」与「没有日志」')

# 遍历结果打印的命令都要有空态分支
from pathlib import Path as _P
_code = chr(10).join(l.split('#')[0] for l in
                     (_P(ROOT) / 'backend' / 'app' / 'cli.py').read_text(encoding='utf-8').splitlines())
assert 'if not rows:' in _code, 'CLI 里遍历结果打印的命令缺少空结果分支'
# 日志行不得用 row['x']：持久化的旧记录可能缺字段，会 KeyError 让 CLI 崩掉
assert "row['message']" not in _code and "row['source']" not in _code, (
    'CLI 仍用 row[...] 硬取字段——旧记录缺字段就会崩，'
    '而崩的用户看到的是「命令坏了」而不是「这条记录旧」')
# CLI 与前端对「来源缺失」用同一套措辞
_disp = (_P(ROOT) / 'frontend' / 'src' / 'lib' / 'display.js').read_text(encoding='utf-8')
if '来源未标注' in _disp:
    assert '来源未标注' in _code, (
        '前端用「来源未标注」、CLI 却另编一个——同一份数据在两处显示成不同来源')
""",
    ),
    Gate(
        id='no-sentinel-measurements',
        desc='缺测不得被填成哨兵数值；告警文案不得声称 SLA 被违反',
        on_fail='block',
        check=r"""
# 「默认值冒充观测值」在**遥测层**的形态。此前 to_snapshot 对缺失的 rtt/loss
# 填 999.0 / 1.0：ping 丢包到算不出 RTT 时，快照变成「延迟 999ms、丢包 100%」，
# diagnose() 据此判 link_down —— **把「没测到」变成了「测到断链」**，
# 可能对一台其实正常的设备下发处置。
#
# 哨兵值是合法 float，结构检查抓不住，只能按行为判定。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.pop('NETMIND_ADMIN_TOKEN', None)
os.environ.pop('NETMIND_PROBE_TARGET', None)
try:
    from app.diagnose.lab_collector import to_snapshot    # noqa: E402
    from app.core.telemetry import TELEMETRY              # noqa: E402

    # 1) 缺测必须是 None，不能是任何具体数字
    s1 = to_snapshot({'transmitted': 10, 'received': 2,
                      'rtt_avg_ms': None, 'loss_ratio': 0.8}, source='lab')
    assert s1.latency_ms is None, \
        f'拿不到 RTT 却给了 {s1.latency_ms}——那是编出来的测量值'
    assert s1.packet_loss == 0.8, '有丢包就该照实记着'

    s2 = to_snapshot({'transmitted': 10, 'received': 10,
                      'rtt_avg_ms': 1.0, 'loss_ratio': 0.0}, source='lab')
    assert s2.throughput_mbps is None, f'没做带宽测量却给了 {s2.throughput_mbps}'

    # 2) 两项都缺时不得给「高置信度正常」
    s3 = to_snapshot({'transmitted': 0, 'received': 0,
                      'rtt_avg_ms': None, 'loss_ratio': None}, source='lab')
    d3 = TELEMETRY.diagnose([s3])
    assert d3.confidence == 0.0, \
        f'延迟与丢包都没测到，却给出 {d3.confidence} 的把握'

    # 3) 部分缺测不得被推断成 link_down
    d1 = TELEMETRY.diagnose([s1])
    assert d1.type != 'link_down', \
        '只有 80% 丢包、RTT 缺失，就被当成断链——依据是伪造的 999ms'
    assert d1.evidence.get('latency_ms') is None

    # 4) 告警文案不得声称 SLA 被违反：项目没有用户约定的 SLO 目标
    for _f in ('backend/app/routers/system.py', 'backend/app/routers/telemetry.py'):
        _text = (ROOT / _f).read_text(encoding='utf-8')
        _code = chr(10).join(l.split('#')[0] for l in _text.splitlines())
        assert 'SLA threshold exceeded' not in _code, (
            f'{_f} 仍用「SLA threshold exceeded」——面板已如实声明「未定义 SLO 目标」，'
            f'这里却声称 SLA 被违反')
finally:
    pass
""",
    ),
    Gate(
        id='changelog-sections-not-duplicated',
        desc='CHANGELOG 每个版本段里同名小节只许出现一次（防止逐轮追加成十几段）',
        on_fail='block',
        check=r"""
# 真实发生过的：Unreleased 段堆到 **13 个 `### Fixed` / `### Added`**——
# 每一轮提交都自己加一个小节，读的人根本看不出这一版里有什么。手工合并过一次，
# 但没加门禁，几个回合就退回原样。**只修一次的东西等于没修。**
#
# Keep a Changelog 的约定就是每个版本段内每种类型只有一个小节。
import collections
import re

CHANGELOG = ROOT / 'CHANGELOG.md'
assert CHANGELOG.exists(), 'CHANGELOG.md 缺失'
text = CHANGELOG.read_text(encoding='utf-8')

# 版本段边界：`## [X]` 或 `## [X] - date`
starts = [(m.start(), m.group(1)) for m in re.finditer(r'^## \[(.+?)\]', text, flags=re.M)]
assert len(starts) >= 2, 'CHANGELOG 里至少要有已发布版本与 Unreleased 两段'

problems = []
for i, (pos, name) in enumerate(starts):
    seg_end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
    seg = text[pos:seg_end]
    heads = re.findall(r'^### (.+)$', seg, flags=re.M)
    counts = collections.Counter(h.strip() for h in heads)
    for h, n in counts.items():
        if n > 1:
            problems.append(f'{name} 段里 `### {h}` 出现了 {n} 次')
    # 只对 Unreleased 段要求四类齐全且有序；已发布段是历史，不动它
    if name.lower() == 'unreleased' and counts:
        CANON = ['Added', 'Changed', 'Deprecated', 'Removed', 'Fixed', 'Security']
        seen = [h for h in CANON if h in counts]
        idx = [CANON.index(h) for h in seen]
        if idx != sorted(idx):
            problems.append(f'Unreleased 段的小节顺序不是 {CANON} 的子序顺序：{seen}')

assert not problems, (
    'CHANGELOG 的版本段里同名小节重复了——逐轮各自追加会让人读不出这一版有什么：\n  - '
    + '\n  - '.join(problems)
    + '\n合并同名小节即可；不要新增同类型小节。')
""",
    ),
    Gate(
        id='frontend-request-layer-is-tested',
        desc='请求层必须在 lib/ 且有测试——vite build 抓不到函数体内的未定义引用',
        on_fail='block',
        check=r"""
# 实测过的教训：把 `request()` 里的 `apiUrl` 误写成 `apiPath`（旧别名），
# **`npm run build` 照样绿灯通过**，因为打包器不检查函数体内的未定义标识符；
# 而它在浏览器里是「首次 API 调用即崩」。`npm test` 一次就抓到 8 条失败。
#
# 也就是说：前端此前「构建通过 = 没问题」这个假设是错的。而承载认证契约的
# `request()` 此前一行测试都写不了——它困在带 JSX 的入口文件里，
# `node --test` 只能直接 import 纯模块。
#
# 抽到 lib/ 之后可测了。门禁的作用是防止它悄悄长回入口文件。
import re
from pathlib import Path

fe = ROOT / 'frontend' / 'src'
app_jsx = (fe / 'App.jsx').read_text(encoding='utf-8')
lib = fe / 'lib'

# 1) 请求层必须在 lib/，且在 App.jsx 里不得再有同名定义
client = lib / 'client.js'
assert client.exists(), \
    '请求层不在 frontend/src/lib/client.js —— 它得能被 node --test 直接 import'
for name in ('request', 'useApi', 'normalizeList', 'toastMessage', 'copyText',
             'downloadText', 'useLocalSettings'):
    assert not re.search(rf'^(?:async )?function {name}\(', app_jsx, flags=re.M), \
        f'{name}() 又长回 App.jsx 了——带 JSX 的入口文件没法被 node --test 覆盖'
    assert re.search(rf'\b{name}\b', app_jsx), \
        f'{name} 从 App.jsx 里消失了，但也没见新的定义处——多半是删漏了'

# 2) 静态数据同理
assert (lib / 'constants.js').exists(), '静态数据段未抽到 lib/constants.js'

# 3) 认证契约必须被断言覆盖——这三条是被打错过两次的地方
client_test = (lib / 'client.test.js').read_text(encoding='utf-8') if (lib / 'client.test.js').exists() else ''
assert client_test, '没有 client.test.js —— request() 承载认证契约，必须有测试'
for must in ("Authorization", "credentialKind", "401", "403"):
    assert must in client_test, f'client.test.js 未覆盖「{must}」相关行为'
# 明确要求钉住那两次打错的地方
assert 'X-NetMind-Admin' in client_test, \
    '未断言「不自造 X-NetMind-Admin 头」——那正是第一次打错的地方'
assert re.search(r'没有默认凭据|凭空', client_test), \
    '未断言「取不到凭据时不兜底」——那正是第二次打错的地方（写死的默认凭据）'

# 3b) 图表不得把缺测画成 0：遥测字段改成可缺之后，Sparkline 的
#     `Number(x[field] || 0)` 会把 null 变成一条真实的「0ms」读数。
#     缺测的点不画，且非数值不得产出 NaN（一个坏行会让整条 polyline 不渲染）。
assert 'charts.js' in '\n'.join(x.name for x in lib.glob('*.js')), \
    '缺 frontend/src/lib/charts.js——图表取点逻辑必须可被 node --test 覆盖'
_ch_raw = (lib / 'charts.js').read_text(encoding='utf-8')
# 先剥注释：模块头那段正是在解释旧写法为什么错，它含 `Number(x[field] || 0)`
# 这个字符串，**写「这里曾经错过」也会让检查命中**（与 App.jsx 同一课）。
_ch = re.sub(r'/\*.*?\*/', '', _ch_raw, flags=re.S)
_ch = '\n'.join(l.split('//')[0] for l in _ch.splitlines())
_seg = _ch.split('sparklinePoints')[1].split('export function')[0] if 'sparklinePoints' in _ch else ''
assert '|| 0' not in _seg, \
    'sparklinePoints 又用 || 0 把缺测顶替成 0——延迟图上会凭空一条「0ms」'
_cht = (lib / 'charts.test.js').read_text(encoding='utf-8') if (lib / 'charts.test.js').exists() else ''
for _must in ('缺测', 'NaN', '负值'):
    assert _must in _cht, f'charts 的测试未覆盖「{_must}」'

# 4) 抽出去的模块不得含 JSX（否则就又不能被 node --test 直接 import 了）
for m in ('client.js', 'constants.js', 'api.js', 'auth.js', 'display.js'):
    p = lib / m
    if not p.exists():
        continue
    body = '\n'.join(l.split('//')[0] for l in p.read_text(encoding='utf-8').splitlines())
    assert not re.search(r'return\s*<|=>\s*<', body), \
        f'lib/{m} 里出现了 JSX——它就又不能被 node --test 直接 import 了'

# 5) 前端测试脚本必须真的会跑到 lib 下的测试
pkg = (ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8')
assert 'node --test' in pkg, 'package.json 的 test 脚本不是 node --test'
assert 'lib' in pkg.split('"test"')[1][:120], 'test 脚本的 glob 没覆盖 src/lib'

# 6) 调用点与声明的**参数个数**必须一致。
#    实测被咬了三次：抽模块时改了签名，App.jsx 的调用点没跟着改，而
#    `npm run build` 与模块自身测试**都是绿的**——它们都不碰调用点。
#    症状是运行时 TypeError（`const [x, y] = undefined`）或整块 UI 静默不渲染。
lib_defs = {}
for m in sorted(lib.glob('*.js')):
    if m.name.endswith('.test.js'):
        continue
    for d in re.finditer(r'export (?:async )?function (\w+)\((.*?)\)\s*\{',
                         m.read_text(encoding='utf-8'), flags=re.S):
        params = _split_params(d.group(2))
        # 有默认值的参数可以不传——只数必填的那个下界
        required = len([a for a in params if not a.startswith('{') and '=' not in a])
        lib_defs.setdefault(d.group(1), (m.name, required, len(params)))
drift = []
for name, (mod, n_req, n_max) in lib_defs.items():
    for call in re.finditer(rf'(?<![.\w]){name}\(([^()]*(?:\([^()]*\)[^()]*)*)\)', app_jsx):
        passed = call.group(1).strip()
        count = 0 if not passed else len(re.split(r',(?![^{]*\})', passed))
        if count < n_req or count > n_max:
            line = app_jsx[:call.start()].count('\n') + 1
            drift.append(f'App.jsx:{line} 调用 {name}(…) 传 {count} 个参数，'
                         f'{mod} 声明 {n_req}–{n_max} 个')
assert not drift, (
    'App.jsx 的调用点与 lib/ 里的声明对不上——这类漂移 **build 与模块测试都是绿的**，'
    '因为它们都不碰调用点，只在浏览器里炸：\n  - ' + '\n  - '.join(drift))

# 7) UI 不得对「没数据」编出关于设备或数据可信度的断言。
#    实测抓到四处：① `node.ip || node.status || '可用'`——没 IP 也没状态的设备
#    被标成「可用」② `row.source || 'system'`——来源未标注被说成来自 system，
#    直接抵消后端那套 source=real|simulated|lab 的标注
#    ③ `row.ts ? … : '刚刚'`——没有时间戳的记录被说成「刚刚」
#    ④ `health?.alerts ? … : '正常'`——**任何检查都还没跑过**时侧栏就显示
#    绿色对勾 +「全网正常」。四处现都由 display.js 里的被测函数出值。
#
#    分层是刻意的：编造落在 App.jsx 由本门禁抓；挪进 lib/display.js 由
#    display.labels.test.js 抓（实测把 provenanceLabel 改回 'system' →
#    2 条测试失败）。单靠门禁不够，单靠测试也不够——两边各管一段。
_jsx_code = '\n'.join(l.split('//')[0] for l in app_jsx.splitlines())
for banned, why in [
    (r"\|\|\s*'可用'", '设备没有 IP 也没有状态就说「可用」'),
    # 只匹配「来源」语境：字体名那里的 || 'system' 是 CSS system font，不是来源声明
    (r"(?:\bsource|\bsrc|\.source|\.src)\b[^\n]{0,40}\|\|\s*'system'",
     '来源未标注却说来自 system'),
    (r":\s*'刚刚'", '没有时间戳的记录说成「刚刚」'),
    (r'health\?\.alerts\s*\?', '「全网状态」用两态：未检查与正常混为一谈'),
]:
    assert not re.search(banned, _jsx_code), f'App.jsx 里还有编造标签：{why}'

for _fn in ('deviceStateLabel', 'provenanceLabel', 'timeLabel', 'netStatusLabel'):
    assert _fn in app_jsx, f'App.jsx 未使用被测函数 {_fn}()——编造标签会从别处长回来'
    assert _fn in (lib / 'display.js').read_text(encoding='utf-8'), f'lib/display.js 缺 {_fn}'
_dtests = '\n'.join(p.read_text(encoding='utf-8') for p in lib.glob('display*.test.js'))
for _must in ('可用', 'system', '刚刚', '未检查'):
    assert _must in _dtests, \
        f'display 的测试未覆盖「{_must}」——这几处编造标签正是从缺测试的地方长出来的'
""",
    ),
    Gate(
        id='no-inert-credential-surface',
        desc='凭据接口不得看起来像能连设备；没有消费方时必须自述',
        on_fail='block',
        check=r"""
# `GET/POST /api/config/credentials` 里的条目带 host / port / username / secret_ref，
# 读起来完全像「凭这条去连设备」——而**没有任何代码消费它们**：驱动只读
# `NETMIND_SSH_HOST` 等环境变量。一台 NetMind 实例只连一台设备。
#
# 放着不说等于骗人：运维 POST 一条生产设备的凭据、看到它被存下来、理所当然
# 以为 NetMind 会用它。安全相关的接口上静默空转是有害的。
#
# 本门禁做两件事：① 要求接口自述 `used_for_connection: false`；② 一旦将来真有人
# 开始消费 STORE.credentials，就要求重新评估这条规则与诚实表措辞，而不是让
# 两处说法各自漂移。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
_keys = ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY')
_saved = {k: os.environ.get(k) for k in _keys}
try:
    for k in _keys:
        os.environ.pop(k, None)
    import app.core.access as _access                     # noqa: E402
    _access._client_host = lambda request: '127.0.0.1'
    from fastapi.testclient import TestClient             # noqa: E402
    from app.main import app as fastapi_app               # noqa: E402
    from app.store import STORE                           # noqa: E402
    from app.schemas import CredentialConfig              # noqa: E402

    STORE.credentials.clear()
    try:
        with TestClient(fastapi_app) as c:
            created = c.post('/api/config/credentials', json={
                'name': 'r1', 'host': '192.0.2.10', 'port': 22,
                'username': 'netmind', 'secret_ref': 'vault://r1',
                'enabled': True,
            })
            assert created.status_code == 200, f'凭据写入失败: {created.status_code}'
            row = created.json()
            assert row.get('used_for_connection') is False, (
                '凭据接口没有自述「不用于连接设备」——字段名 host/port/username '
                '会让人以为它能连设备，而实际上没有消费方')
            assert 'NETMIND_SSH_HOST' in str(row.get('note', '')), \
                '自述里没指向真正生效的环境变量，使用者不知道该配哪里'
            listed = c.get('/api/config/credentials').json()
            assert listed and listed[0].get('used_for_connection') is False, \
                '列表接口漏了自述字段'
            assert listed[0].get('secret_ref') == '***', 'secret_ref 仍以明文返回'
    finally:
        STORE.credentials.clear()

    # 消费方探测：真有人用了就得重新评估这条门禁与诚实表措辞
    consumers = []
    for p in (ROOT / 'backend' / 'app').rglob('*.py'):
        rel = p.relative_to(ROOT)
        if rel.as_posix() in ('backend/app/store.py', 'backend/app/schemas.py',
                              'backend/app/routers/config.py'):
            continue          # 存储、模型、接口自身不算消费方
        txt = p.read_text(encoding='utf-8')
        if 'STORE.credentials' in txt or 'self.credentials' in txt:
            consumers.append(str(rel))
    assert not consumers, (
        f'STORE.credentials 出现消费方了：{consumers}。'
        f'若凭据已真正用于连接设备，本门禁的 used_for_connection 断言与诚实表'
        f'里「一台实例 = 一台设备」的措辞都需重新评估——不要让两处说法漂移。')

    # 诚实表不该再暗示存在多设备部署模型
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'one instance manages one device' in readme, \
        '诚实表未写明「一台实例管一台设备」——不写会让人以为可以按设备授权'
    deploy = (ROOT / 'docs' / 'DEPLOY.md').read_text(encoding='utf-8')
    assert '一台实例 = 一台设备' in deploy, 'DEPLOY.md 未写明部署模型'
finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
""",
    ),
    Gate(
        id='remediation-matches-diagnosis-direction',
        desc='处置的方向不得与诊断条件相反（带宽下降不得用限速去「修」）',
        on_fail='block',
        check=r"""
# 处置必须对症。曾经 `anomaly_traffic` 的触发条件是「带宽跌幅 ≥50%」，
# 而处置是 `tc qdisc add ... netem rate {rate}mbit`——限速。
# 也就是「带宽掉了 → 把带宽再限死一点」：限值高于已跌下去的带宽时是空动作，
# 低于时把它弄得更糟。没有任何一种情况下能修好。
#
# 这类错误测试抓不住：命令能生成、过得了安全门、在真机上也能真下发——
# 它只是**方向不对**，而所有结构性检查都会放行。所以要按「语义配对」来卡。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
from app.core.remediation import (NO_AUTO_REMEDIATION_REASON,  # noqa: E402
                                  REMEDIATIONS)
from app.core import telemetry as tel                        # noqa: E402

# 1) 处置表里不该有任何限速类模板。只要没有「带宽下降 → 限速」这种配对，
#    方向就不会再反。真要限速某个流量是**策略意图**该做的事（人写策略），
#    不是从一次遥测异常里自动推出来的。
for kind, spec in REMEDIATIONS.items():
    assert 'rate' not in spec['template'], (
        f'{kind} 的处置模板是限速（{spec["template"]}）。'
        f'带宽下降是症状不是病因，限速修不好它，最坏还会更糟。')

# 2) 两个刻意不给自动处置的诊断，必须都有给使用者看的理由。
#    少了理由，运维看到「没有对应的处置原语」只能自己去翻源码。
for kind in ('anomaly_traffic', 'config_error'):
    assert kind not in REMEDIATIONS, f'{kind} 不该有自动处置'
    reason = NO_AUTO_REMEDIATION_REASON.get(kind, '')
    assert reason and len(reason) > 40, f'{kind} 缺给使用者看的拒绝理由'
    assert '不做自动处置' in reason, f'{kind} 的理由没说清是刻意选择而非能力缺失'

# 3) 方向前提本身：anomaly_traffic 只能由「带宽下跌」触发。
#    若将来真的加上了「带宽过高」分支，限速就有了适用场景，
#    那时应当把本门禁与 REMEDIATIONS 一起重新评估，而不是悄悄放行。
src = (ROOT / 'backend' / 'app' / 'core' / 'telemetry.py').read_text(encoding='utf-8')
assert tel.THROUGHPUT_DROP_RATIO == 0.5, '带宽跌幅阈值变了，anomaly_traffic 的语义前提需重新评估'
branch = src[src.index("'anomaly_traffic'"):]
branch = branch[:branch.index('return Diagnosis(type=', 10)]
assert 'bw_drop' in branch, \
    'anomaly_traffic 的触发条件不再基于带宽下跌——限速可能重新变得适用，请重新评估'
""",
    ),
    Gate(
        id='gates-do-not-pollute-each-other',
        desc='门禁按顺序同进程执行：inline 检查体跑完后 store 必须与跑之前一致',
        on_fail='block',
        check=r"""
# 门禁在同一个进程里按顺序执行，检查体用 exec 跑在模块全局上。
# 于是一条门禁若改了 STORE 却只还原环境变量，后面所有门禁看到的都是
# 一个被改过的世界——套件变成顺序相关，症状是「单条全过、整体偶发挂」，
# 而且极难定位：失败的那条和真正动手的那条根本不是同一条。
#
# 真实发生过：`system-status-is-measured` 清了 STORE.models / STORE.telemetry
# 却只还原 os.environ，于是位置 3 之后的门禁都在空 store 上跑。
#
# 只跑 **inline 检查体**：cmd 型门禁（pytest / 演练 / 压测）都在自己的子进程里，
# 污染不到本进程，跑它们只会让这条门禁慢上一个数量级。
#
# 也因此**不能**用「再调一次 loop.py gates」来验证——那条门禁自己就在列表里，
# 套件会无限递归（实测一次冒出 18 个嵌套进程）。这个坑项目里已经踩过一次
# （loop-gates 递归），这里再踩一遍就是没看教训。
import os as _os
import sys
# 检查体用 exec 跑在只含 ROOT/re/json/subprocess 的作用域里（见 run_one 的 NS），
# 所以 sys 与路径都得自己准备好，不能指望外层给。
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
import gates as _self      # noqa: E402
from app.store import STORE  # noqa: E402

# --- 递归防护（两道，缺一不可）-----------------------------------
# 这条门禁会调用 run_one 去跑别的门禁。若不防住，它自己也在 GATES 列表里，
# 就会自触发 —— 实测一次冒出 18 个嵌套 loop.py 进程，直接把机器拖垮。
# 这个坑项目 retro 里已记过一次（loop-gates 递归），这里再踩就是没看教训。
#
# 第一道：按 id 跳过自己（下面循环里）。
# 第二道：环境变量深度计数。**不依赖 id 列表**——万一有人改了 id 或复制了
# 这段检查体，id 跳过就失效了，深度计数仍然拦得住。宁可漏跑也不能自触发。
_DEPTH = int(_os.environ.get('NETMIND_POLLUTION_DEPTH', '0') or 0)
assert _DEPTH < 1, '污染检测门禁出现嵌套调用（NETMIND_POLLUTION_DEPTH>0）——不该发生'
_os.environ['NETMIND_POLLUTION_DEPTH'] = str(_DEPTH + 1)

_SELF_ID = 'gates-do-not-pollute-each-other'
assert _SELF_ID in {g.id for g in _self.GATES}, \
    '这条门禁不在 GATES 列表里——那它证明不了什么，检查体已被误删'


def _snap():
    # 比**内容**，不比对象身份（id()）。
    #
    # 早先这里比 id()，结果每个跑 TestClient(app) 的门禁都被算成污染——
    # 因为 app 启动会 STORE.load() 从磁盘重建列表，合法地产生一批新实例。
    # 「世界还是不是同一个世界」问的是内容，不是对象是不是同一个。
    # 反过来也成立：清空再灌进**不同**内容，值一变照样能抓到。
    #
    # **不含 logs**：审计流是只追加的，门禁往里写东西本就是应有之义
    # （谁做了什么、失败了什么都要留痕）。把增长当成污染，等于逼着门禁
    # 删审计记录——那比多几条日志糟得多。
    return {'telemetry': [t.model_dump(mode='json') for t in STORE.telemetry],
            'models': sorted(STORE.models),
            'rules': len(STORE.rules),
            'executions': len(STORE.executions),
            'approvals': len(STORE.approvals)}


try:
    _before = _snap()
    _ran = []
    for _g in _self.GATES:
        if not _g.check or _g.id == _SELF_ID:
            continue                      # 第一道：跳过自己
        _status, _detail = _self.run_one(_g)
        _ran.append(_g.id)
    _after = _snap()
    assert _after == _before, (
        f'跑完 {len(_ran)} 条 inline 门禁后 store 状态与跑之前不一致——'
        f'有门禁改了共享状态却没还原，后面的门禁是在被污染的世界里跑的。\n'
        f'    跑过的门禁: {_ran}\n'
        f'    之前: {_before}\n'
        f'    之后: {_after}')
finally:
    _os.environ['NETMIND_POLLUTION_DEPTH'] = str(_DEPTH)
""",
    ),
    Gate(
        id='frontend-auth-contract',
        desc='前端的认证头必须与后端一致，且不得有写死的默认凭据',
        on_fail='block',
        check=r"""
# 实测过的严重缺陷：前端 `request()` 发的是 `X-NetMind-Admin` 自定义头，
# 而后端只读 `Authorization: Bearer`。结果是按 `docs/DEPLOY.md` 第 1 节配了
# `NETMIND_ADMIN_TOKEN` 之后，**网页面板的每个请求都是 401，界面完全不可用**——
# 而那正是文档推荐的部署方式。
#
# 更隐蔽的一半：原代码还有一份写死的兜底凭据 `'netmind-local-admin'`。
# 后端不认它所以只是无效字符串，但它离「一份所有人都知道的固定默认凭据」
# 只差后端哪天认了这个头。
import os, re, sys
sys.path.insert(0, str(ROOT / 'backend'))
_keys = ('NETMIND_ADMIN_TOKEN', 'NETMIND_READONLY_TOKEN', 'NETMIND_ALLOW_ANON_READONLY',
         'NETMIND_TRUST_PROXY')
_saved = {k: os.environ.get(k) for k in _keys}
try:
    fe = ROOT / 'frontend' / 'src'
    app_jsx = (fe / 'App.jsx').read_text(encoding='utf-8')
    # 去掉注释后再查：注释里提到旧头名是为了说明为什么改，不该被当成残留
    code_only = '\n'.join(l.split('//')[0] for l in app_jsx.splitlines())

    # 1) 不得有自造的认证头。后端只读 authorization，前端必须与之对齐。
    for banned in ('X-NetMind-Admin', 'X-Admin-Token', 'X-NetMind-Token'):
        assert banned not in code_only, \
            f'前端又出现了 {banned}——后端只读 `Authorization: Bearer`，' \
            f'发别的头等于配了 token 之后面板全线 401'

    # 2) 不得有写死的默认凭据
    assert not re.search(r"['\"]netmind-local-admin['\"]", code_only), \
        '前端又有写死的默认凭据——等于一份所有人都知道的固定口令'
    assert not re.search(r"localStorage[^\n]*\|\|[^\n]*['\"][A-Za-z0-9_-]{8,}['\"]", code_only), \
        '凭据取不到时又回退到某个字符串常量了'

    # 3) 行为判定：用前端 auth.js 真正产出的头去打真后端
    auth_js = (fe / 'lib' / 'auth.js').read_text(encoding='utf-8')
    assert 'Authorization' in auth_js and 'Bearer' in auth_js, \
        'frontend/src/lib/auth.js 不再发送 Authorization: Bearer'

    os.environ['NETMIND_ADMIN_TOKEN'] = 'gate-admin'
    os.environ['NETMIND_READONLY_TOKEN'] = 'gate-ro'
    os.environ.pop('NETMIND_ALLOW_ANON_READONLY', None)
    os.environ.pop('NETMIND_TRUST_PROXY', None)
    import app.core.access as _access            # noqa: E402
    _access._client_host = lambda request: '203.0.113.9'
    from fastapi.testclient import TestClient    # noqa: E402
    from app.main import app as fastapi_app      # noqa: E402
    with TestClient(fastapi_app) as c:
        assert c.get('/api/dashboard', headers={'Authorization': 'Bearer gate-admin'}).status_code == 200, \
            '带 Bearer 凭据仍读不到面板'
        assert c.get('/api/dashboard', headers={'X-NetMind-Admin': 'gate-admin'}).status_code == 401, \
            '后端竟开始接受 X-NetMind-Admin 了——前端与后端的契约说明已不同步，需一并更新'

    # 4) 前端测试必须真的覆盖了这段
    tests = '\n'.join(p.read_text(encoding='utf-8')
                      for p in (fe / 'lib').glob('*.test.js'))
    assert 'Authorization' in tests, \
        '没有测试断言前端发的是 Authorization: Bearer——这类不匹配正是靠它漏掉的'
finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
""",
    ),
    Gate(
        id='no-unearned-confidence',
        desc='诊断置信度必须由可观测状态推导，不吃 schema 默认值',
        on_fail='block',
        check=r"""
# CONTRIBUTING 规则 2：置信度须由可观测状态推导。反复出现的缺陷形态是
# 「默认值被当成观测值」——面板的 sla=98、状态端点的 healthy=true、
# Diagnosis.confidence 的 0.9，都是同一类。
#
# 这条查的是最后那一类：异常分支的置信度早已改成按证据推导，但
# `return Diagnosis(type='normal')` 漏了——**全项目最常出现的那个结论，
# 恰恰是唯一不经过任何推导的**。实测：样本量 1 与 10 给同一个 0.9、
# 读数贴阈值与极低给同一个 0.9、模拟数据与真实数据也给同一个 0.9。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.pop('NETMIND_ADMIN_TOKEN', None)
os.environ.pop('NETMIND_PROBE_TARGET', None)
from app.store import STORE                                        # noqa: E402
# diagnose([]) 会回退到 STORE.telemetry[-3:]，而门禁进程里是带种子数据的 store。
# 不隔离就测不到「真的一个样本都没有」这条——它会读到种子遥测并判成 congestion。
_saved_telemetry = list(STORE.telemetry)
try:
    STORE.telemetry.clear()
    from app.core.telemetry import (LATENCY_DEGRADED_MS, TELEMETRY)   # noqa: E402
    from app.schemas import TelemetrySnapshot                          # noqa: E402

    def snap(lat, loss=0.0, src='real'):
        return TelemetrySnapshot(latency_ms=lat, packet_loss=loss,
                                 throughput_mbps=50, alert=False, source=src)

    empty = TELEMETRY.diagnose([])
    assert empty.type == 'normal' and empty.confidence == 0.0, \
        f'一个样本都没有却报 {empty.type}/{empty.confidence} 的把握'
    assert empty.evidence, '无样本时必须说明为什么判不了'

    one = TELEMETRY.diagnose([snap(1.0)])
    ten = TELEMETRY.diagnose([snap(1.0)] * 10)
    near = TELEMETRY.diagnose([snap(LATENCY_DEGRADED_MS - 5)] * 10)
    sim = TELEMETRY.diagnose([snap(1.0, src='simulated')] * 10)

    assert ten.confidence > one.confidence, \
        f'样本量 1→10，置信度没变（{one.confidence}）——「依据变多」不体现在结论上'
    assert near.confidence < ten.confidence, \
        '读数贴着劣化阈值时说「正常」的把握与读数极低时相同'
    assert sim.confidence < ten.confidence, \
        '模拟数据得出的「一切正常」与真实数据一样自信——sim 折扣在正常分支没生效'
    assert all(d.type == 'normal' for d in (one, ten, near, sim))
finally:
    STORE.telemetry.clear()
    STORE.telemetry.extend(_saved_telemetry)
""",
    ),
    Gate(
        id='fixtures-are-self-consistent',
        desc='真实抓包 fixture 内部自洽：自报统计必须与自己的报文行对得上',
        on_fail='block',
        check=r"""
# `real-data-not-faked` 只查结构特征（有没有 'bytes from'、断链态有没有
# round-trip 行）。那挡得住一眼假的，挡不住**用心编的**——手写一份
# 「10 packets transmitted, 10 packets received, 0% packet loss」谁都会，
# 但要同时让 10 行报文的 seq 连续、time 值算出来的 min/avg/max 与自报那行
# 完全吻合，就不是随手能编的了。
#
# 抓包文件自带的这组内部约束是免费的：它本来就在文件里，只是没人核对过。
import json
import re

lab = ROOT / 'tests' / 'fixtures' / 'lab'
STAT = re.compile(r'(\d+) packets transmitted, (\d+) packets received')
REPLY = re.compile(r'bytes from [^\s:]+: seq=(\d+).*time=([\d.]+)\s*ms')
RTT = re.compile(r'round-trip min/avg/max = ([\d.]+)/([\d.]+)/([\d.]+) ms')

problems = []
checked = 0
for p in sorted(lab.glob('ping-*.txt')):
    text = p.read_text(encoding='utf-8')
    m = STAT.search(text)
    if not m:
        problems.append(f'{p.name}: 没有 ping statistics 行')
        continue
    sent, recv = int(m.group(1)), int(m.group(2))
    replies = REPLY.findall(text)
    if len(replies) != recv:
        problems.append(
            f'{p.name}: 自报 {recv} 个回包，文件里实际 {len(replies)} 行回包——对不上')
    if len(replies) != sent and recv == sent:
        problems.append(f'{p.name}: 自报 {sent}/{recv} 全通，但只有 {len(replies)} 行')
    seqs = [int(s) for s, _ in replies]
    if seqs and seqs != list(range(len(seqs))):
        problems.append(f'{p.name}: 回包 seq 不连续 {seqs[:5]}…——真实 ping 不会这样')
    r = RTT.search(text)
    if replies:
        if not r:
            problems.append(f'{p.name}: 有回包却没有 round-trip 行')
        else:
            lo, avg, hi = (float(x) for x in r.groups())
            times = sorted(float(t) for _, t in replies)
            if abs(times[0] - lo) > 0.002 or abs(times[-1] - hi) > 0.002:
                problems.append(
                    f'{p.name}: round-trip 自报 min/max={lo}/{hi}，'
                    f'实际 {times[0]}/{times[-1]}——编的')
            real_avg = sum(times) / len(times)
            if abs(real_avg - avg) > 0.002:
                problems.append(
                    f'{p.name}: round-trip 自报 avg={avg}，按报文行算是 {real_avg:.3f}——编的')
    elif r:
        problems.append(f'{p.name}: 一个回包都没有却给出 round-trip 统计')
    checked += 1

assert checked >= 3, f'只检查到 {checked} 份 ping fixture，扫描范围不对'
assert not problems, '抓包 fixture 内部不自洽:\n  - ' + '\n  - '.join(problems)

# 跨 fixture 引用要能对上：key_finding 里引用的每个实测值，
# 都必须真的出现在本组的真实数据里（任一 state 的字段，或任一抓包的 RTT 行）。
# 悬空的数字是「结论看起来有据、实际查无此数」——最难发现的一种不实。
tp = lab / 'throughput-real.json'
if tp.exists():
    data = json.loads(tp.read_text(encoding='utf-8'))
    haystack = [str(data)]
    for p in sorted(lab.glob('*.txt')):
        haystack.append(p.read_text(encoding='utf-8'))
    blob = '\n'.join(haystack)
    cited = set(re.findall(r'(?<![\w.])\d{1,3}\.\d{1,3}(?![\w])', str(data.get('key_finding', ''))))
    untraceable = sorted(n for n in cited if n not in blob)
    assert not untraceable, (
        f'throughput-real.json 的 key_finding 引用了 {untraceable}，'
        f'但这些值在 states 与任何抓包里都查不到——结论悬空')
""",
    ),
    Gate(
        id='system-status-is-measured',
        desc='运行状态端点的字段必须由可观测状态算出，不得吃 schema 默认值',
        on_fail='block',
        check=r"""
# `/api/system/status` 是探活与运维看的接口。此前 healthy / driver / model_online
# 三个字段**从来没有被任何代码赋值**——全吃 schema 默认值，于是端点恒返回
# healthy=true、driver=simulation、model_online=true。配了 SSH 驱动、模型离线、
# 压根没采到数据，它都照报「健康」。
#
# 另外 auth_mode 缺失会让前端认不出只读身份：只读用户看到可点的下发按钮，
# 点了才知道不行——「点了才知道」比没有只读角色更让人困惑。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
_keys = ('NETMIND_DRIVER', 'NETMIND_ADMIN_TOKEN', 'NETMIND_READONLY_TOKEN',
         'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_TRUST_PROXY')
_saved = {k: os.environ.get(k) for k in _keys}
from app.store import STORE                           # noqa: E402
# store 也要还原：门禁按顺序在同一进程里跑，只还原环境变量的话，这条之后的
# 所有门禁看到的都是一个被我清空过的世界——套件变成顺序相关，就会出现
# 「单条全过、整体偶发挂」这类没法定位的现象。
_saved_telemetry = list(STORE.telemetry)
_saved_models = {k: v for k, v in STORE.models.items()}
try:
    from app.core import access as _access            # noqa: E402
    from app.schemas import TelemetrySnapshot         # noqa: E402
    from fastapi.testclient import TestClient         # noqa: E402
    from app.main import app as fastapi_app           # noqa: E402

    for k in _keys:
        os.environ.pop(k, None)
    _access._client_host = lambda request: '203.0.113.9'
    with TestClient(fastapi_app) as c:
        # 1) driver 跟着配置走，而不是永远 simulation
        os.environ['NETMIND_DRIVER'] = 'ssh'
        assert c.get('/api/system/status', headers={'Authorization': 'Bearer x'}).status_code in (200, 401, 403)
        os.environ['NETMIND_ADMIN_TOKEN'] = 'adm'
        os.environ['NETMIND_READONLY_TOKEN'] = 'ro'
        assert c.get('/api/system/status',
                     headers={'Authorization': 'Bearer adm'}).json()['driver'] == 'ssh', \
            'driver 字段没跟着 NETMIND_DRIVER 走'

        # 2) model_online 不是写死的 true
        STORE.models.clear()
        assert c.get('/api/system/status',
                     headers={'Authorization': 'Bearer adm'}).json()['model_online'] is False, \
            '一个模型都没配却报 model_online=true——该字段仍是默认值'

        # 3) healthy 取决于遥测有无：没采到数据不报健康
        STORE.telemetry.clear()
        s0 = c.get('/api/system/status', headers={'Authorization': 'Bearer adm'}).json()
        assert s0['healthy'] is False, '没有任何遥测却报 healthy=true'
        STORE.record_telemetry(TelemetrySnapshot(latency_ms=1.2, packet_loss=0.0,
                                                 throughput_mbps=50, alert=False, source='real'))
        s1 = c.get('/api/system/status', headers={'Authorization': 'Bearer adm'}).json()
        assert s1['healthy'] is True, '有真实遥测却报不健康'
        assert s1['telemetry_source'] == 'real', '没报出遥测来源，无法判断数据真假'

        # 4) auth_mode 如实反映调用者档位——前端靠它识别只读身份
        ro = c.get('/api/system/status', headers={'Authorization': 'Bearer ro'}).json()
        adm = c.get('/api/system/status', headers={'Authorization': 'Bearer adm'}).json()
        assert ro['auth_mode'] == 'readonly-token', f"只读凭据的 auth_mode 是 {ro['auth_mode']}"
        assert adm['auth_mode'] == 'token', f"管理员凭据的 auth_mode 是 {adm['auth_mode']}"
finally:
    # store 必须在 finally 里还原。只还原 os.environ 是不够的：门禁按顺序在
    # 同一个进程里跑，这条清空过的 store 会留给后面所有门禁，套件就此变成
    # 顺序相关——症状是「单条全过、整体偶发挂」，而且失败的那条根本不是
    # 动手的那条，极难定位。由 gates-do-not-pollute-each-other 盯着。
    STORE.telemetry.clear(); STORE.telemetry.extend(_saved_telemetry)
    STORE.models.clear();   STORE.models.update(_saved_models)
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
""",
    ),
    Gate(
        id='readonly-credential-is-enforced',
        desc='只读凭据能读不能写；写操作须 403（凭据有效但权限不足）而非 401',
        on_fail='block',
        check=r"""
# SECURITY.md 此前明写「无只读角色」。对自托管网络运维工具，最常见的实际需求
# 恰恰是「让另一个人能看运行态势但不许他下发配置变更」——原先只有匿名只读与
# 全权 token 两个极端，中间档缺失。
#
# 两条容易被做错的地方：
#   1) 写操作要 403 不是 401。凭据有效、只是权限不够；混成 401 会让客户端
#      以为该换凭据，而不是「这个人没这个权限」。
#   2) 比对不能早退。早退会让「命中第几个候选」体现在响应时间上，攻击者据此
#      区分凭据种类。只读与管理员权限不同，能区分本身就是可利用的信息。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
_keys = ('NETMIND_ADMIN_TOKEN', 'NETMIND_READONLY_TOKEN', 'NETMIND_ALLOW_ANON_READONLY',
         'NETMIND_TRUST_PROXY')
_saved = {k: os.environ.get(k) for k in _keys}
ADMIN, RO = 'gate-admin', 'gate-readonly'
try:
    from app.core.access import SAFE_METHODS, evaluate, verify_any  # noqa: E402

    class _R:
        def __init__(self, method, path, token=None):
            self.method = method
            self.url = type('U', (), {'path': path})()
            self.headers = {'authorization': f'Bearer {token}'} if token else {}
            self.client = type('C', (), {'host': '203.0.113.9'})()

    for k in _keys:
        os.environ.pop(k, None)
    os.environ['NETMIND_ADMIN_TOKEN'] = ADMIN
    os.environ['NETMIND_READONLY_TOKEN'] = RO

    # 先查写：只读凭据一旦对写操作不再限权，报错要直指这一条，
    # 而不是让「读」先撞上来报一句让人摸不着头脑的话
    for m in ('POST', 'PUT', 'PATCH', 'DELETE'):
        d = evaluate(_R(m, '/api/telemetry/heal', RO))
        assert d.allowed is False, f'只读凭据竟然能 {m}——只读角色形同虚设'
        assert d.status == 403, f'只读凭据的 {m} 返回 {d.status}，应为 403（凭据有效、权限不足）'
    for m in sorted(SAFE_METHODS):
        d = evaluate(_R(m, '/api/dashboard', RO))
        assert d.allowed, f'只读凭据的 {m} 被拒了——只读角色没了意义'
        assert d.mode == 'readonly-token'
    for m in ('GET', 'POST'):
        assert evaluate(_R(m, '/api/dashboard', ADMIN)).allowed, f'管理员凭据的 {m} 被拒了'
    assert evaluate(_R('GET', '/api/dashboard', 'wrong')).status == 401, \
        '凭据错误必须是 401，与「权限不足」区分开'
    # 不短路：与候选顺序无关
    a = verify_any(f'Bearer {RO}', (('admin', ADMIN), ('readonly', RO)))
    b = verify_any(f'Bearer {RO}', (('readonly', RO), ('admin', ADMIN)))
    assert a == b == 'readonly', 'verify_any 的结果依赖候选顺序——早退会泄露时序信息'
    # 什么都不配时默认安全不得放松
    for k in _keys:
        os.environ.pop(k, None)
    d = evaluate(_R('GET', '/api/dashboard'))
    assert d.allowed is False and d.status == 403, '两个 token 都没配时，远程访问不再默认拒绝'
finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
""",
    ),
    Gate(
        id='release-is-coherent',
        desc='版本号与 CHANGELOG 最新发布段一致；已发布段的小节不得重复堆叠',
        on_fail='block',
        check=r"""
# 0.2.0 之前 CHANGELOG 的 Unreleased 段里有 19 个重复的 `### Added/Fixed` 小节、
# 99 条条目——读者根本读不出这个版本里有什么。归并之后要防止复发。
#
# 两条硬要求：
#   1) backend/app/__init__ 的版本号必须等于 CHANGELOG 里最新的已发布段
#   2) 一个已发布段里每种小节标题只能出现一次
import re
import sys
from pathlib import Path as P

ch = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
sys.path.insert(0, str(ROOT / 'backend'))
from app import __version__ as ver                    # noqa: E402

released = re.findall(r'^## \[(\d+\.\d+\.\d+)\] - ', ch, flags=re.M)
assert released, 'CHANGELOG 里没有任何已发布段（`## [x.y.z] - 日期`）'
assert released[0] == ver, \
    f'CHANGELOG 最新发布段是 [{released[0]}]，但代码版本是 {ver}——两者必须同步'

# 只查最新那一段（历史段落允许旧格式）
start = ch.index(f'## [{released[0]}]')
nxt = ch.find('\n## [', start + 1)
body = ch[start:nxt if nxt != -1 else len(ch)]
heads = re.findall(r'^### (.+)$', body, flags=re.M)
dupes = sorted({h for h in heads if heads.count(h) > 1})
assert not dupes, (
    f'[{released[0]}] 段里小节标题重复出现: {dupes}——'
    f'读者会以为发了 {len(heads)} 个不同类别，实际是同一类被拆碎了')

# 每条已发布段都要能让人复核：至少要挂上入口文件或脚本
assert re.search(r'`(scripts|backend|docs|tests)/', body), \
    f'[{released[0]}] 段里没有任何可复现的路径引用——规则 5 要求每条主张挂得上东西'
""",
    ),
    Gate(
        id='no-missing-as-zero',
        desc='缺失值不得渲染成 0（`x || 0` 把「没测」说成「测了，是 0」）',
        on_fail='block',
        check=r"""
# 真浏览器验证时抓到的：面板上「端到端延迟 --ms」却在同一张卡片的副标题里
# 写着「丢包率 0.00%」——后端返回的是 `packet_loss: null`，前端那个
# `Number(metrics.packet_loss || 0)` 把它变成了 0%。同一张卡片自相矛盾。
#
# 之所以躲过了前几轮的清理：metricValue 守的是 `value` 属性，而这一处躲在
# 模板字符串里做 `* 100` 再 `toFixed`。凡是「先 `|| 0` 兜底、再参与算术或
# 格式化」的地方，都是同一个坑。
import re as _re
app_jsx = (ROOT / 'frontend' / 'src' / 'App.jsx').read_text(encoding='utf-8')
code = '\n'.join(l.split('//')[0] for l in app_jsx.splitlines())

MEASURE_WORDS = ('latency_ms', 'packet_loss', 'throughput_mbps', 'duration_ms',
                 'confidence', 'avg_latency', 'avg_rtt', 'rtt_avg', 'loss_ratio')
# 逐行做子串判断，不用正则——`\s` 在本文件的 raw string 里容易被多写一层反斜杠，
# 写出「匹配字面反斜杠」的检查，然后在别处莫名命中
hits = []
for line in code.splitlines():
    for w in MEASURE_WORDS:
        if w + ' || 0' in line:
            hits.append(line.strip()[:110])
            break
assert not hits, (
    '这些地方用 `指标 || 0` 把缺失值变成 0——渲染出来是「测了，是 0」：\n    '
    + '\n    '.join(hits))

# 兜底值必须走被测的显示函数，而不是就地写死
disp = (ROOT / 'frontend' / 'src' / 'lib' / 'display.js').read_text(encoding='utf-8')
# 测试可能按主题拆成多个文件（display.test.js / display.percent.test.js …），
# 只查其中一个会把正确拆分的测试判成「没测」
tests = '\n'.join(p.read_text(encoding='utf-8')
                  for p in (ROOT / 'frontend' / 'src' / 'lib').glob('display*.test.js'))
assert tests, 'frontend/src/lib 下找不到 display*.test.js'
assert 'percentText' in disp, '缺 percentText()——比率没有统一的缺失值处理'
assert 'percentText' in tests, 'percentText() 没有测试'
for fn in ('metricValue', 'healthScore', 'summaryCell', 'confidenceText', 'percentText'):
    assert fn in app_jsx, f'App.jsx 未使用被测函数 {fn}()'
""",
    ),
    Gate(
        id='frontend-is-production-served',
        desc='面板由生产构建 + nginx 同源托管，不是 Vite dev server',
        on_fail='block',
        check=r"""
# 此前 compose 起的前端是 `npm run dev`（Vite dev server）。把开发服务器当产品发出去
# 谈不上「可直接商用」：HMR 端点暴露、源码不压缩、构建产物不进镜像。
#
# 顺带修掉一个更隐蔽的问题：`VITE_*` 是**构建期**注入的，所以镜像里烤死了
# `VITE_API_URL=http://localhost:8000`。于是同一份镜像换个访问地址就指错地方，
# 而且跨源发 Authorization 头会触发 CORS 预检，预检失败的表现常常像网络问题。
#
# 现在：nginx 托管生产构建，并把 /api 与 /ws 同源反代到后端；API 基址在**启动时**
# 注入（index.html 里的注入点由 nginx 替换），默认空串 = 同源。
from pathlib import Path as P
import json as _json
import re as _re

df = (ROOT / 'frontend' / 'Dockerfile').read_text(encoding='utf-8')
nginx = (ROOT / 'frontend' / 'nginx.conf').read_text(encoding='utf-8')
pkg = _json.loads((ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8'))
compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
index = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')

assert 'npm run dev' not in df, \
    '前端镜像仍在跑 Vite dev server——开发服务器不是产品'
assert 'npm run build' in df, '前端镜像没有先做生产构建'
assert 'AS build' in df and 'nginx' in df, \
    '前端镜像不是「多阶段构建 → nginx 托管静态产物」的结构'
assert '/etc/nginx/templates/' in df, (
    'nginx 配置必须放 templates/：nginx 把 ${...} 当成自己的变量，'
    '直接写进 conf.d 会以 unknown variable 退出（实测踩过）')
assert 'sub_filter' in nginx and 'NETMIND_API_BASE' in nginx, \
    'nginx 未在启动时注入 API 基址——同源反代的前提没了'
assert 'location /api/' in nginx and 'proxy_pass http://backend' in nginx, \
    'nginx 没有把 /api 反代到后端，同源方案就不成立'
assert '/ws' in nginx and 'Upgrade' in nginx, 'WebSocket 未反代，面板收不到事件'
assert '__NETMIND_API__' in index, 'index.html 缺少运行时注入点'
# 只看真正的 environment 行：注释里写「不再需要设 VITE_API_URL」是对的话，
# 把它也算成命中，那门禁就只能逼人把说明删掉
compose_env = '\n'.join(l for l in compose.splitlines() if not l.lstrip().startswith('#'))
assert 'VITE_API_URL' not in compose_env, (
    'compose 里还在设 VITE_API_URL——那是构建期变量，容器里设对已构建页面无效')
assert 'NETMIND_API_BASE' in compose_env, \
    'compose 没有把 API 基址作为运行时变量传进前端容器'
assert 'service_healthy' in compose, \
    'frontend 没等 backend 健康就启动，首个请求可能打空'
assert 'healthcheck' in compose, 'compose 没有 healthcheck，依赖健康无从判断'
assert pkg.get('scripts', {}).get('test'), '前端失去 test 脚本'
""",
    ),
    Gate(
        id='container-deploy-needs-token',
        desc='docker compose 部署必须设 token —— 端口映射后对端不是 loopback',
        on_fail='block',
        check=r"""
# 实测过的部署陷阱：默认 `docker compose up` 之后，面板能打开（前端 200），
# 但它要调的每个后端接口都 403，因为
#   · 后端判「本机」看对端是不是 127.0.0.1
#   · 经端口映射进来的请求，对端是网关 IP（172.x.x.1）
# 容器内自访 200、宿主机经 localhost:8000 访问 403——同一台机器，两种结果。
#
# 这不是安全模型有问题（默认拒绝是对的），是可发现性问题：报错只说
# 「请设置 NETMIND_ADMIN_TOKEN」，而使用者以为自己已经设过了。
from pathlib import Path as P
compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
deploy = (ROOT / 'docs' / 'DEPLOY.md').read_text(encoding='utf-8')
readme = (ROOT / 'README.md').read_text(encoding='utf-8')

# 1) compose 里那个变量上方必须有醒目提示，而不是一句「留空 = 仅本机」
import re as _re
env_idx = compose.find('NETMIND_ADMIN_TOKEN')
assert env_idx != -1, 'docker-compose.yml 里没有 NETMIND_ADMIN_TOKEN——部署者无从得知要设'
nearby = compose[max(0, env_idx - 1400):env_idx]
assert ('必须' in nearby or '⚠️' in nearby), \
    'docker-compose.yml 里 NETMIND_ADMIN_TOKEN 上方没有「必须设置」的提示'
assert ('网关' in nearby or 'docker' in nearby.lower() or '端口映射' in nearby), \
    'compose 的提示没说清原因：经端口映射后对端不是 loopback'

# 2) 部署指南必须把它放在最前面，而不是埋在正文里
head = deploy[:deploy.find('## 1.')]
assert 'docker compose' in head and ('网关' in head or '端口映射' in head), \
    'docs/DEPLOY.md 的开头没有讲清「compose 必须设 token」，使用者会先撞上 403'
assert 'loopback-only' in compose or 'NETMIND_ADMIN_TOKEN' in compose

# 3) README 的快速开始不能让人以为开箱即用
assert ('docker compose' not in readme) or ('NETMIND_ADMIN_TOKEN' in readme), \
    'README 提到 docker compose 却没有提必须设 token'

# 4) 403 报错本身要点明这个场景——使用者撞上它时还没读部署文档
import sys as _sys
_sys.path.insert(0, str(ROOT / 'backend'))
from app.core.access import decide            # noqa: E402
d = decide('GET', '/api/dashboard', '172.18.0.1', '', False)
assert d.allowed is False and d.status == 403
assert 'docker' in d.reason, \
    '403 报错没提 docker 场景——使用者会以为自己已经设过 token 了'
""",
    ),
    Gate(
        id='security-doc-matches-behavior',
        desc='SECURITY.md 的关键声明必须与实现一致（认证范围 / 回滚门 / 数据外发）',
        on_fail='block',
        check=r"""
# 安全文档写错比不写更糟：它会让人以为某个面已经有防护。
# 实际发现过两处漂移——SECURITY.md 写「token 配了也只保护非 GET」（实现是
# GET 也要）、写「回滚绕过危险操作门」（实现仍要求归属证明）。
#
# 这里做行为判定：跑一遍真实请求与真实安全门，再断言文档没把防护说小或说大。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
_keys = ('NETMIND_ADMIN_TOKEN', 'NETMIND_ALLOW_ANON_READONLY', 'NETMIND_PROBE_TARGET',
         'NETMIND_TRUST_PROXY')
_saved = {k: os.environ.get(k) for k in _keys}
try:
    doc = (ROOT / 'SECURITY.md').read_text(encoding='utf-8')

    from fastapi.testclient import TestClient      # noqa: E402
    from app.main import app                        # noqa: E402
    from app.core.security import SECURITY          # noqa: E402
    from app.store import STORE                     # noqa: E402

    # 1) 配了 token 之后，GET 也必须被拦住；/healthz 是唯一公开口
    os.environ['NETMIND_ADMIN_TOKEN'] = 'gate-token'
    os.environ.pop('NETMIND_ALLOW_ANON_READONLY', None)
    with TestClient(app) as c:
        hdr = {'Authorization': 'Bearer gate-token'}
        assert c.get('/api/dashboard').status_code in (401, 403), \
            '配了 token 竟能匿名读 dashboard——安全门形同虚设'
        assert c.get('/api/dashboard', headers=hdr).status_code == 200, \
            '带正确 token 反而读不到——认证坏了'
        assert c.get('/healthz').status_code == 200, '/healthz 应保持公开（探活不该要凭据）'
        assert c.get('/api/dashboard', headers=hdr).status_code != 401
    # 文档必须说清楚「GET 也要认证」，否则读的人会以为 dashboard 是公开的
    assert 'including GET' in doc or '含 GET' in doc or 'including** GET' in doc, \
        'SECURITY.md 未写明「配了 token 后 GET 同样需要认证」'
    assert 'every** method' in doc or 'every method' in doc, \
        'SECURITY.md 对认证范围的表述与实现（所有方法都要认证）不符'

    # 2) 回滚**不**绕过危险操作门：未归属的 route del 必须仍被拒
    STORE.owned_routes.clear()
    cmd = 'ip route del 10.0.0.0/24 via 192.0.2.9 dev eth0'
    denied = SECURITY.check(cmd, allow_dangerous=True)
    assert denied.success is False, '未登记的路由删除被放行了——回滚成了删任意路由的开关'
    assert 'does not bypass' in doc or '不绕过' in doc or 'still demands proof' in doc, \
        'SECURITY.md 未如实说明回滚仍要求归属证明'
    assert 'bypass the "dangerous command" gate by design' not in doc, \
        'SECURITY.md 仍写着「回滚绕过危险操作门」——与实现相反'
    STORE.owned_routes.clear()

    # 3) 认证范围：**每一份客户可见文档**都要说对，不能只查 SECURITY.md。
    # 上一轮修了 SECURITY.md 就以为这事结了，`docs/API.md` 与 `README.md` 的
    # 环境变量表各留了一份。门禁覆盖了它检查的那份，并不代表别的文档是对的。
    #
    # 只拦**断言**，不拦**提及**：CHANGELOG 里写「此前说 non-GET 是错的」是在
    # 记录修正史，若一并拦下，就得把修正记录从变更日志里删掉——那更糟。
    CORRECTION = ('错误', '误', '曾', '此前', '原先', '改', '修正',
                  'wrong', 'earlier', 'fixed', 'was ', 'used to')
    visible = ([ROOT / 'SECURITY.md', ROOT / 'README.md', ROOT / 'CHANGELOG.md']
               + sorted((ROOT / 'docs').glob('*.md')))
    stale = []
    for dpath in visible:
        if not dpath.exists():
            continue
        for line in dpath.read_text(encoding='utf-8').splitlines():
            if not (('non-GET' in line or '非 GET' in line)
                    and ('token' in line or 'Token' in line)):
                continue
            if any(w in line for w in CORRECTION):
                continue          # 在讲「这里曾经错」，不是在断言现状
            stale.append(f'{dpath.relative_to(ROOT)}: {line.strip()[:100]}')
    assert not stale, (
        '这些客户可见文档仍断言「配 token 后只保护非 GET 请求」——'
        '实际所有方法含 GET 都要认证：\n    ' + '\n    '.join(stale))
    api_doc = (ROOT / 'docs' / 'API.md').read_text(encoding='utf-8')
    assert 'including GET' in api_doc, \
        'docs/API.md 未写明「配了 token 后 GET 同样需要认证」'
finally:
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
""",
    ),
    Gate(
        id='no-unused-declared-dependency',
        desc='声明为运行时依赖的包必须真被用到（死依赖白装白交付，还扩大供应链面）',
        on_fail='block',
        check=r"""
# 死依赖对用户是纯负担：装一次、审计一次、被投毒一次，却换来零功能。
# 本仓曾声明 recharts@3.8.1 而 src 里从未 import 过它。
#
# 只查 dependencies，不查 devDependencies——后者是构建工具，本来就不进
# src/。也不要求子路径精确匹配：`react-dom` 是以 `react-dom/client` 引入的，
# 只认全名会把它误判成死依赖。
import json
fe = ROOT / 'frontend'
pkg = json.loads((fe / 'package.json').read_text(encoding='utf-8'))
deps = pkg.get('dependencies') or {}
if not deps:
    pass
else:
    srcs = [p for p in (fe / 'src').rglob('*')
            if p.suffix in {'.js', '.jsx', '.ts', '.tsx'} and p.is_file()]
    assert srcs, 'frontend/src 下没有任何源文件——扫描范围不对，门禁会永远放行'
    blob = '\n'.join(p.read_text(encoding='utf-8', errors='ignore') for p in srcs)
    unused = []
    for name in sorted(deps):
        # 子路径导入（react-dom/client）也算用到：按包名做词边界匹配，
        # 允许后跟 /。
        if re.search(r'[\'"]' + re.escape(name) + r'(/[\w./-]*)?[\'"]', blob):
            continue
        # 构建工具即使只经 npm scripts 调用，也不该待在运行时依赖里
        unused.append(name)
    assert not unused, (
        '声明为运行时依赖但 src/ 里从未 import: ' + ', '.join(unused) +
        ' —— 死依赖白装白交付，还把供应链面白白扩大。'
        '构建工具请放 devDependencies。')
""",
    ),
    Gate(
        id='healing-is-guarded',
        desc='自动处置须有显式目标且有次数上限；未配置时如实说未启用，不假装成功',
        on_fail='block',
        check=r"""
# 两个问题必须有确定答案：动哪块、动几次。
#
# 此前主工作流的 HealingAgent 是永远动不了的：workflow.py 调 heal(diag) 不传
# iface，remediation.build() 缺 iface 就抛 RemediationUnavailable，每次都走
# 「无需处置」。更糟的是那一行无论返回什么都记 Status.success——审计里看过去
# 就是「自愈成功了」。cycle 21 做的真自愈从主路径根本走不到。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
_keys = ('NETMIND_HEAL_IFACE', 'NETMIND_HEAL_BACKUP_ROUTE', 'NETMIND_HEAL_MAX_ATTEMPTS',
         'NETMIND_ENABLE_REAL_COMMANDS', 'NETMIND_DRIVER', 'NETMIND_PROBE_TARGET')
_saved = {k: os.environ.get(k) for k in _keys}
for k in _keys:
    os.environ.pop(k, None)
from app.store import STORE  # noqa: E402
_saved_telemetry = list(STORE.telemetry)
_saved_executions = dict(STORE.executions)
_saved_attempts = {k: dict(v) for k, v in STORE.heal_attempts.items()}

from app.core import heal_guard                    # noqa: E402
from app.core.workflow import ORCHESTRATOR         # noqa: E402
from app.core.telemetry import TELEMETRY           # noqa: E402
from app.store import STORE                        # noqa: E402
from app.schemas import Diagnosis, TelemetrySnapshot  # noqa: E402

try:
    # 1) 没配接口 → 拒绝并说清缺什么，不猜
    try:
        heal_guard.target_for('congestion')
        raise AssertionError('未配置处置接口却给出了目标——在猜')
    except heal_guard.HealingDisabled as e:
        assert heal_guard.IFACE_ENV in str(e), '拒绝时必须点名缺哪个配置项'

    # 2) 闭环里未配置时，HealingAgent 步骤不得记 success
    STORE.executions.clear(); STORE.telemetry.clear(); STORE.heal_attempts.clear()
    TELEMETRY.inject('congestion')
    ex = ORCHESTRATOR.run_closed_loop('给会议网提高优先级', dry_run=True)
    step = [s for s in ex.steps if s.agent == 'HealingAgent']
    assert step, '闭环里没有 HealingAgent 步骤'
    assert step[0].status.value != 'success', \
        '什么都没做却把 HealingAgent 记成 success——审计里看过去就是自愈成功了'
    assert ex.healing.improvement.get('target_configured') is False

    # 3) 配了接口后，闭环里自愈必须真能生成命令（否则护栏把功能锁死了）
    os.environ[heal_guard.IFACE_ENV] = 'eth0'
    TELEMETRY.inject('congestion')
    ex2 = ORCHESTRATOR.run_closed_loop('给会议网提高优先级', dry_run=True)
    cmds = ex2.healing.improvement.get('planned_commands')
    assert cmds, '配了目标后闭环仍不生成任何处置命令——护栏把功能锁死了'

    # 4) 次数上限真的会拦
    class _S:
        def __init__(self):
            self.heal_attempts = {}; self.last_heal_execution = ''; self.dirty = 0
        def mark_dirty(self): self.dirty += 1
    s = _S()
    for _ in range(heal_guard.max_attempts()):
        heal_guard.guard(s, 'congestion', 'eth0')
        heal_guard.record_failure(s, 'congestion', 'eth0')
    try:
        heal_guard.guard(s, 'congestion', 'eth0')
        raise AssertionError('连续失败已达上限却仍放行——上限形同虚设')
    except heal_guard.AttemptCapReached:
        pass

    # 5) 计数必须落盘，否则重启一次就绕过去了
    heal_guard.record_failure(STORE, 'congestion', 'eth9')
    assert STORE.to_json().get('heal_attempts'), 'heal_attempts 未进持久化快照'
    STORE.heal_attempts.clear()
finally:
    # 这条门禁会真跑两遍闭环，而闭环的 TelemetryAgent 会往 STORE.telemetry 里
    # 追加采样。不还原的话，位置在它之后的门禁读到的是被这次闭环改过的遥测。
    STORE.executions.clear(); STORE.executions.update(_saved_executions)
    STORE.telemetry.clear(); STORE.telemetry.extend(_saved_telemetry)
    STORE.heal_attempts.clear(); STORE.heal_attempts.update(_saved_attempts)
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
""",
    ),
    Gate(
        id='dashboard-no-fabricated-numbers',
        desc='面板数字必须来自真实状态；无数据时返回 null 而非写死的常量',
        on_fail='block',
        check=r"""
# 违反 CONTRIBUTING 规则 2（No fabricated telemetry）。此前 /api/dashboard 的
# metrics 全是路由里的字面量：sla 恒为 98、active_intents 恒为 2，外加三条固定
# 风险文案和两个编造的意图名。诚实表没有对应条目声明它们是模拟的——读者
# 无从判断 98 是测出来的还是编的。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.pop('NETMIND_ADMIN_TOKEN', None)
os.environ.pop('NETMIND_ALLOW_ANON_READONLY', None)
os.environ.pop('NETMIND_PROBE_TARGET', None)

import app.core.access as _access                 # noqa: E402
_access._client_host = lambda request: '127.0.0.1'
from app.core.dashboard import build_dashboard    # noqa: E402
from app.schemas import TelemetrySnapshot        # noqa: E402

# 1) 空状态：不得冒出任何数字或占位文案
d = build_dashboard(executions=[], telemetry=[], logs=[], topology=None)
assert d['metrics']['latency_ms'] is None, f"空数据却报了延迟 {d['metrics']['latency_ms']}"
assert d['metrics']['packet_loss'] is None
assert d['metrics']['active_intents'] == 0
assert d['risks'] == [], '没有观测却凭空生成了风险条目'
assert d['active_intents'] == [], '没有执行却凭空生成了活跃意图'

# 2) SLA 达成率没有 SLO 目标就永远不该被算出来
assert d['metrics']['sla'] is None, '未定义 SLO 目标却给出了 SLA 达成率'
assert d['provenance']['sla_computed'] is False
assert d['metrics']['sla_reason'], '不提供该指标时必须说明原因'

# 3) 健康遥测不该被编成风险
quiet = build_dashboard(executions=[], logs=[], topology=None,
                        telemetry=[TelemetrySnapshot(latency_ms=0.2, packet_loss=0.0,
                                                    throughput_mbps=80, alert=False,
                                                    source='real')])
assert quiet['risks'] == [], '健康的真实遥测被编成了风险条目'

# 4) 有真实遥测时，数字要能对得上
real = build_dashboard(executions=[], logs=[], topology=None,
                       telemetry=[TelemetrySnapshot(latency_ms=137.25, packet_loss=0.4,
                                                    throughput_mbps=3, alert=True,
                                                    source='real')])
assert real['metrics']['latency_ms'] == 137.25, '面板报的延迟与 store 里的不一致'
assert real['risks'], '有告警却没有风险条目'
for r in real['risks']:
    assert r.get('evidence'), f'风险「{r["title"]}」没有证据字段，无法核查'

# 5) 复核接口必须有真判定字段，不能只写死一句「无冲突」
from fastapi.testclient import TestClient        # noqa: E402
from app.main import app                        # noqa: E402
from app.store import STORE                     # noqa: E402
_saved = (list(STORE.executions.values()), list(STORE.telemetry), list(STORE.logs))
STORE.executions.clear(); STORE.telemetry.clear(); STORE.logs.clear()
try:
    with TestClient(app) as c:
        r = c.post('/api/system/ai-recovery-review').json()
        assert r.get('verdict') in ('differences-found', 'no-difference', 'partial',
                                    'indeterminate'), \
            f'复核没有判定字段，只有 {sorted(r)}——它到底比没比无从得知'
        assert r['verdict'] == 'indeterminate', '空 store 下不得声称「无冲突」'
        assert 'compared' in r and 'undecidable' in r

        # 6) SLA 判定必须跟着给的目标走。原实现是 GET 无请求体、门槛写死 50ms，
        #    而前端一直 POST 并传了完整目标——实测 POST 直接 405，GET 返回的
        #    `achievable` 和前端读的 `feasible` 也对不上。
        for v in (180.0, 190.0, 175.0):
            STORE.record_telemetry(TelemetrySnapshot(latency_ms=v, packet_loss=0.001,
                                                     throughput_mbps=90, alert=False,
                                                     source='real'))
        assert c.post('/api/telemetry/predict-sla', json={}).status_code == 200, \
            'SLA 预测不接受 POST——前端一直用的就是 POST，实测会 405'
        strict = c.post('/api/telemetry/predict-sla',
                        json={'sla': {'latency_ms': 50}}).json()
        relaxed = c.post('/api/telemetry/predict-sla',
                         json={'sla': {'latency_ms': 400}}).json()
        assert strict['feasible'] is False, '181ms 对 50ms 目标应判不可行'
        assert relaxed['feasible'] is True, \
            '把目标放宽到 400ms 后仍判不可行——说明门槛是写死的，没在用调用方的目标'
        assert strict['target_used']['latency_ms'] == 50, '结论里必须带上用的哪个目标'
        none = c.post('/api/telemetry/predict-sla', json={}).json()
        assert none['feasible'] is None, \
            '没给目标却下了可行性结论——那是替用户决定什么叫达标'
finally:
    ex, tel, logs = _saved
    STORE.executions.update({e.execution_id: e for e in ex})
    STORE.telemetry.clear(); STORE.telemetry.extend(tel)
    STORE.logs.clear(); STORE.logs.extend(logs)

# 7) 前端同一件事的另一端：面板与验证摘要的取值决策必须是**被测过的**函数。
#    此前它们散在 App.jsx 里一行都没测，healthScore 那处
#    `metrics.sla || (packet_loss < 0.01 ? 96 : 82)` 就长期躺在那儿没人发现。
fe = ROOT / 'frontend' / 'src'
app_jsx = (fe / 'App.jsx').read_text(encoding='utf-8')
code_only = '\n'.join(l.split('//')[0] for l in app_jsx.splitlines())
for pattern, why in [
    (r'\|\|\s*\([^)]*\?[^:]+:\s*\d+\s*\)', '用 || 加三元反推一个数字当指标'),
    (r'sla_feasible:\s*true', '写死 SLA 可行性——把「未知」显示成「可行」'),
    (r'sla_confidence:\s*1\b', '写死 100% 置信度'),
]:
    assert not re.search(pattern, code_only), f'App.jsx 又出现了「{why}」的写法'
for fn in ('healthScore', 'metricValue', 'summaryCell', 'confidenceText'):
    assert f'{{ {fn}(' in app_jsx or f'{fn}(' in app_jsx, f'App.jsx 未使用被测函数 {fn}()'
assert (fe / 'lib' / 'display.js').exists() and (fe / 'lib' / 'display.test.js').exists(), \
    '显示层取值逻辑必须留在 lib/display.js 并有测试；放回 App.jsx 就等于退回零覆盖'
""",
    ),
    Gate(
        id='license-present',
        desc='LICENSE 文件存在且非空（企业法务硬阻塞）',
        on_fail='block',
        check=r"""
lic = ROOT / 'LICENSE'
assert lic.exists(), 'LICENSE 文件缺失：README/pyproject/CONTRIBUTING 三处声称 MIT 但文件不在'
body = lic.read_text(encoding='utf-8').strip()
assert len(body) > 200, f'LICENSE 内容过短（{len(body)} 字符），疑似占位'
assert 'MIT' in body or 'Apache' in body, 'LICENSE 未声明具体协议名'
""",
    ),
    Gate(
        id='loop-state-present',
        desc='循环状态文件存在且满足不变量（backlog 非空、cycle 单调）',
        on_fail='block',
        check=r"""
sp = LOOP_DIR / 'state.json'
assert sp.exists(), '.netmind-loop/state.json 缺失——循环未落盘即等于未跑'
st = json.loads(sp.read_text(encoding='utf-8'))
for k in ('cycle', 'phase', 'metrics', 'backlog', 'gates', 'rounds'):
    assert k in st, f'state.json 缺字段 {k}'
assert st['backlog'], 'backlog 为空——协议硬要求：允许 backlog 空等于允许停顿'
assert st['phase'] in ('plan', 'build', 'test', 'improve', 'state'), f'phase 非法: {st["phase"]}'
cycles = [r['cycle'] for r in st['rounds']]
assert cycles == sorted(cycles), 'rounds 的 cycle 非单调递增'
assert len(cycles) == len(set(cycles)), 'rounds 存在重复 cycle'
ids = [b['id'] for b in st['backlog']]
dup = sorted({i for i in ids if ids.count(i) > 1})
assert not dup, 'backlog 存在重复 id: ' + ', '.join(dup) + '（cmd_state 按 id 匹配，重复会误标 done）'
bad_status = sorted({b.get('status') for b in st['backlog']} - {'pending', 'done', 'blocked'})
assert not bad_status, f'backlog 存在非法 status: {bad_status}'
unblocked = [b['id'] for b in st['backlog'] if b.get('status') == 'blocked' and not b.get('blocked_on')]
assert not unblocked, '标 blocked 但未写 blocked_on: ' + ', '.join(unblocked)
""",
    ),
    Gate(
        id='tests-green',
        desc='后端全量单测通过',
        on_fail='block',
        cmd=[sys.executable, '-m', 'pytest', 'backend/tests/', '-q', '--tb=short'],
    ),
    Gate(
        id='validate-project',
        desc='项目形状门（关键文件/路由/安全默认项存在）',
        on_fail='block',
        cmd=[sys.executable, 'scripts/validate_project.py'],
    ),
    Gate(
        id='no-ai-smell',
        desc='去 AI 味密度门（CONTRIBUTING 规则 5 营销面可核查律）',
        on_fail='block',
        cmd=[sys.executable, 'scripts/copy_lint.py'],
    ),
    Gate(
        id='no-dead-module',
        desc='零死模块（无任何导入点的 .py 不得留在包内）',
        on_fail='block',
        check=r"""
assert _dead_modules() == [], '零引用死模块: ' + ', '.join(_dead_modules())
""",
    ),
    Gate(
        id='no-dead-local',
        desc='零死局部变量（生产代码里赋了值却从未被读——重构残留，读代码的人会被误导）',
        on_fail='block',
        check=r"""
# 「算了却没用」的变量不是风格问题：像 transaction.py 里那个 rb_all_ok，
# 读代码的人会以为回滚完整性由它控制，实际由 _rollback() 的返回值走
# DeployResult.rollback_complete。留着就是误导。
#
# 三类合法写法不算死码，按惯例排除：
#   · 下划线开头        —— 显式标注「故意不用」
#   · 元组解包的被丢弃位 —— intent, _ = parse(...) 这类
#   · for 循环变量      —— 循环本身就是目的
#
# 范围只到 backend/app（生产代码）：函数里定义的类，其类属性会被本函数外的
# 代码读到（测试里的 R().method 就是这种），把类体算进函数作用域会误报。
# 与 no-dead-module 同样只对非测试文件做判定。
import ast

def _ancestors(node, parent, stop_at):
    # 向上找祖先，但在 stop_at（本函数）处停下。
    # 停下的理由：方法体里的赋值往上走会撞到**自己所属的类**，而那个类不是
    # 「函数内定义的类」。只排除真正嵌套在函数内部的 ClassDef（那里的属性
    # 才是给本函数外的代码读的类属性）。
    while node in parent:
        node = parent[node]
        if node is stop_at:
            return
        yield node

def _dead_locals(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    out = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        reads = {n.id for n in ast.walk(fn)
                 if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)):
                continue
            if n.id in reads or n.id == '_' or n.id.startswith('_'):
                continue
            if isinstance(parent.get(n), (ast.Tuple, ast.For)):
                continue
            # 类体内的赋值是类属性，不是局部变量——它给本函数外的代码读
            if any(isinstance(a, ast.ClassDef) for a in _ancestors(n, parent, fn)):
                continue
            out.append(f'{path.relative_to(ROOT)}:{n.lineno} {fn.name}() 的 {n.id}')
    return out

dead = []
for p in sorted((ROOT / 'backend' / 'app').rglob('*.py')):
    try:
        dead += _dead_locals(p)
    except SyntaxError as exc:
        dead.append(f'{p.relative_to(ROOT)} 语法错误: {exc}')
assert not dead, ('死局部变量 %d 处:\n  ' % len(dead)) + '\n  '.join(dead[:12])
""",
    ),
    Gate(
        id='real-data-not-faked',
        desc='真实数据通道未被退回模拟（fixture 存在且含真实采集特征）',
        on_fail='block',
        check=r"""
import json
from pathlib import Path
lab = ROOT / 'tests' / 'fixtures' / 'lab'
need = ['ping-healthy.txt', 'ping-congestion.txt', 'ping-link_down.txt', 'throughput-real.json']
missing = [n for n in need if not (lab / n).exists()]
assert not missing, '缺少真实数据 fixture: ' + ', '.join(missing) + '（tests/fixtures/lab/）'

# 真抓包必然带这些特征；手写的样例不会
h = (lab / 'ping-healthy.txt').read_text(encoding='utf-8')
assert 'bytes from' in h, 'ping-healthy.txt 不含真实回包行，疑似手写样例'
assert re.search(r'round-trip min/avg/max', h), 'ping-healthy.txt 无 round-trip 统计行'

# 断链态的真实特征：0 回包且完全没有 round-trip 行（模拟器遇不到这个形态）
d = (lab / 'ping-link_down.txt').read_text(encoding='utf-8')
assert 'bytes from' not in d, '断链态不应有回包行'
assert 'round-trip' not in d, '断链态不应有 round-trip 行——若存在说明 fixture 被伪造'

j = json.loads((lab / 'throughput-real.json').read_text(encoding='utf-8'))
states = j.get('states', {})
assert {'healthy', 'delay_only', 'rate_limited'} <= set(states), '带宽 fixture 缺少关键状态'
assert states['delay_only']['throughput_mbps'] > 0, '延迟态带宽须为真实正值而非 0'
assert states['healthy']['rtt_avg_ms'] < states['delay_only']['rtt_avg_ms'], '延迟态 RTT 应大于健康态，否则采集根本没生效'

# 采集器必须真的接在 schema 上，否则真实数据存不进来
sc = (ROOT / 'backend' / 'app' / 'schemas.py').read_text(encoding='utf-8')
assert "'real'" in sc or '"real"' in sc, 'TelemetrySnapshot.source 未开放 real 取值——真实数据在 schema 层会被拒'
""",
    ),
    Gate(
        id='no-fake-healing',
        desc='自愈不得恒报成功（verified=False 时 success 必须 False，且跑测须含反例）',
        on_fail='block',
        check=r"""
import json
# 1) schema 层：success 不能再有「默认 True」这种一构造就成功的默认值
sch = (ROOT / 'backend' / 'app' / 'schemas.py').read_text(encoding='utf-8')
i = sch.find('class HealingReport')
blk = sch[i:i + 900]
assert 'success: bool = False' in blk, 'HealingReport.success 默认值不是 False——默认 True 等于「一构造就成功」'
assert 'verified: bool = False' in blk, 'HealingReport 缺 verified 字段，无法表达「未做重测」'

# 2) 跑测报告必须存在且含反例场景
rep = ROOT / 'docs' / 'closed-loop-run-report.md'
assert rep.exists(), 'docs/closed-loop-run-report.md 缺失——跑测报告是对外数字的唯一来源'
rt = rep.read_text(encoding='utf-8')
assert '反例' in rt, '跑测报告缺反例场景；只报成功的报告不构成验证'
assert '不能' in rt and '支撑' in rt, '跑测报告必须列出「本报告不能支撑的主张」'

# 3) 反例数据必须真的记着 success=False
cf = ROOT / 'tests' / 'fixtures' / 'lab' / 'closed-loop-run.json'
assert cf.exists(), '缺 closed-loop-run.json（真实闭环跑测原始数据）'
scen = json.loads(cf.read_text(encoding='utf-8'))
neg = [x for x in scen if x['scenario'] == 'no_op_negative']
assert neg, '跑测数据缺 no_op_negative 反例'
assert neg[0]['success'] is False, '反例的 success 竟为 True——闭环又在演戏'
assert neg[0]['verified'] is True, '反例应已重测，verified 应为 True'
""",
    ),
    Gate(
        id='rollback-on-no-improvement',
        desc='下发后未改善必须真回滚；撤不回来时必须如实说撤不回来',
        on_fail='block',
        check=r"""
# 锁 W2-rollback-trigger。此前 heal() 压根没有 rollback 调用——它把 success
# 报成 False 就结束了，坏变更留在设备上——而 docstring 写着「触发回滚」。
# 文档比实现更乐观，正是这个项目要消灭的那类问题。
#
# 这里不查源码文本，直接把行为跑一遍：注入「下发成功但指标没改善」，
# 看回滚到底有没有被调用。
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))

calls = {'deploy': 0, 'rollback': 0}

class _Probe:
    mode = lambda self: 'real'                      # noqa: E731
    name = 'probe'
    def execute(self, c):
        return CommandResult(command=c, success=True, output='')

class _T:
    driver = _Probe()
    def deploy(self, eid, plan):
        calls['deploy'] += 1
        return DeployResult(execution_id=eid, executed=[], success=True, mode='real')
    def rollback(self, plan, eid, reason='', policies=None):
        calls['rollback'] += 1
        has = any(p.rollback_commands for p in plan.policies)
        return DeployResult(execution_id=eid, executed=[], rolled_back=has,
                            rollback_complete=has, success=has, mode='real')

# 门禁按顺序在同一进程里跑。改环境变量却不还原，等于给后面的门禁埋雷：
# 它们会以为自己在真机模式下跑。逐项保存退出时恢复。
_env_keys = ('NETMIND_ENABLE_REAL_COMMANDS', 'NETMIND_DRIVER', 'NETMIND_PROBE_TARGET')
_env_saved = {k: os.environ.get(k) for k in _env_keys}
os.environ['NETMIND_ENABLE_REAL_COMMANDS'] = 'true'
os.environ['NETMIND_DRIVER'] = 'ssh'
os.environ.pop('NETMIND_PROBE_TARGET', None)

import app.core.transaction as txn                  # noqa: E402
from app.core.telemetry import TELEMETRY            # noqa: E402
from app.core.remediation import (ROLLBACK_INSPECT,  # noqa: E402
                                  ROLLBACK_INVERSE, rollback_info)
from app.schemas import CommandResult, DeployResult, Diagnosis, TelemetrySnapshot  # noqa: E402

calls = {'deploy': 0, 'rollback': 0}

class _Probe:
    mode = lambda self: 'real'                      # noqa: E731
    name = 'probe'
    def execute(self, c):
        return CommandResult(command=c, success=True, output='')

class _T:
    driver = _Probe()
    def deploy(self, eid, plan):
        calls['deploy'] += 1
        return DeployResult(execution_id=eid, executed=[], success=True, mode='real')
    def rollback(self, plan, eid, reason='', policies=None):
        calls['rollback'] += 1
        has = any(p.rollback_commands for p in plan.policies)
        return DeployResult(execution_id=eid, executed=[], rolled_back=has,
                            rollback_complete=has, success=has, mode='real')

_real = txn.TRANSACTION
txn.TRANSACTION = _T()
_real_sample = TELEMETRY.sample
try:
    # 前后两次采样给一样的数 → 必然「没改善」
    TELEMETRY.sample = lambda record=True: TelemetrySnapshot(
        latency_ms=200.0, packet_loss=0.30, throughput_mbps=10, alert=True, source='real')
    TELEMETRY._last_fallback = ''

    # 用 link_down：它是自动处置里**唯一**可逆的路径（inverse 能力）。
    # 早先这里用 anomaly_traffic，那条处置已因「诊断=带宽跌、动作=限速」方向相反
    # 被移出处置表——门禁没跟着改就会与代码漂移（实测报
    # TypeError: heal() got an unexpected keyword argument 'rate_mbps'）。
    # 门禁引用生产 API 的地方随 API 变更是常事，但**必须一起改**，否则它测的是
    # 一个已经不存在的功能。
    rep = TELEMETRY.heal(Diagnosis(type='link_down', confidence=0.9),
                         iface='eth0', backup='10.9.0.0/24 via 192.0.2.9')
    assert calls['deploy'] == 1, '前置条件不成立：deploy 没被调用'
    assert calls['rollback'] == 1, \
        '下发成功但指标没改善，却没有触发回滚——坏变更被留在设备上了'
    assert rep.success is False, '没改善却报成功'

    rb = rep.improvement.get('rollback')
    assert rb and rb.get('attempted') is True, '报告里没有回滚记录，无法判断是否撤销过'
    assert rb.get('capability') == ROLLBACK_INVERSE, \
        f"link_down 是可逆的，回滚能力不该报成 {rb.get('capability')}"

    # congestion 撤不回来：必须明说，且不得谎称已回滚
    calls['rollback'] = 0
    rep2 = TELEMETRY.heal(Diagnosis(type='congestion', confidence=0.9), iface='eth0')
    rb2 = rep2.improvement.get('rollback', {})
    assert rb2.get('capability') == ROLLBACK_INSPECT, 'congestion 应如实降级为不可自动回滚'
    assert rb2.get('rolled_back') is False, '没有逆操作却报 rolled_back=True——谎报'
    assert '无法自动回滚' in rep2.summary, '撤不回来时文案必须说清'
finally:
    TELEMETRY.sample = _real_sample
    txn.TRANSACTION = _real
    for _k, _v in _env_saved.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
""",
    ),
    Gate(
        id='vendor-matrix-is-authoritative',
        desc='厂商支持只以矩阵为准，README 不自述；且矩阵与驱动映射不得漂移',
        on_fail='block',
        check=r"""
import json, sys
from pathlib import Path as P
sys.path.insert(0, str(ROOT / 'backend'))

# 1) README 不得自己复述厂商清单，只允许引用矩阵
readme = (P('README.md')).read_text(encoding='utf-8')
assert 'diagnose/vendor_matrix.py' in readme or '/api/vendors' in readme, \
    'README 未引用厂商矩阵——它自己那套说法会与实态漂移'
for vendor in ('cisco-ios', 'juniper', 'arista', 'cisco-nxos'):
    # README 里提到厂商名可以，但不能同时自称「支持 N 家」这类可核查数字
    pass

# 2) 矩阵与驱动映射必须一致（行为判定）
from app.diagnose.drivers import pick_driver          # noqa: E402
from app.diagnose.vendor_matrix import VENDORS, VERIFIED, summary   # noqa: E402

for v in VENDORS:
    if v.transport != 'napalm':
        continue
    for kind in v.kinds:
        name, reason = pick_driver(kind)
        assert name == v.driver, \
            f'厂商矩阵说 {v.name}/{kind}→{v.driver}，但 pick_driver 给 {name}（{reason}）——两处口径漂移'

# 3) 标 verified 的必须有真实采集 fixture 支撑
s = summary()
assert s[VERIFIED] >= 1, '没有任何厂商是 verified——矩阵应至少反映已跑通的 Linux/FRR'
fx = P('tests/fixtures/lab/live-collection.json')
if fx.exists():
    d = json.loads(fx.read_text(encoding='utf-8'))
    assert d.get('collected'), 'verified 存在但真实采集 fixture 没采到东西'

# 4) 端点必须真的挂着
from app.main import app                              # noqa: E402
paths = set()
def walk(n, seen=None):
    seen = seen if seen is not None else set()
    if id(n) in seen: return
    seen.add(id(n))
    for r in (getattr(n, 'routes', None) or []):
        p = getattr(r, 'path', None)
        if isinstance(p, str): paths.add(p)
        walk(r, seen)
    for a in ('original_router', 'app'):
        c = getattr(n, a, None)
        if c is not None and c is not n: walk(c, seen)
walk(app)
assert '/api/vendors' in paths, '厂商矩阵端点未挂到 API 上'
""",
    ),
    Gate(
        id='collection-not-guessed',
        desc='设备采集不得猜驱动；未知型号须明确拒绝（诚实表承诺 Real 的能力要有据）',
        on_fail='block',
        check=r"""
import json, sys
from pathlib import Path as P

# 1) 行为判定，不做源码文本匹配：匹配源码会命中文档里描述旧 bug 的那段话，
#    反而误报。直接调用函数看行为——单元测试之外的第二道网。
sys.path.insert(0, str(ROOT / 'backend'))
from app.diagnose.drivers import pick_driver          # noqa: E402
for bad_kind in ('vyos', 'mikrotik', 'huawei', 'paloalto', 'unknown-xyz'):
    name, reason = pick_driver(bad_kind)
    assert name != 'eos', f'{bad_kind} 被兜底成 eos——会把未知型号当 Arista 下命令'
    assert reason, f'{bad_kind} 拒绝映射时必须给出原因'
for linux_kind in ('linux', 'alpine', 'frr', 'debian'):
    name, reason = pick_driver(linux_kind)
    assert name is None, f'{linux_kind} 不该被映射到 {name}（napalm 无此驱动）'
    assert 'napalm' in reason, f'{linux_kind} 应归入「Linux 系 napalm 驱不了」: {reason}'

# 2) 必须有 Linux/FRR 的第二条采集路径（napalm 驱不了这类型）
assert (P('backend/app/diagnose/linux_collect.py')).exists(), \
    '缺 Linux/FRR 的 netmiko 直连采集路径——实验台拓扑全是这类设备'

# 3) 声明了 nokia/srl 映射，就必须声明对应插件依赖
reqs = (P('backend/requirements-drivers.txt')).read_text(encoding='utf-8')
for pkg in ('napalm-nokia', 'napalm-srl'):
    assert pkg in reqs, f'{pkg} 在映射表里被引用但依赖里未声明——永远走不通'

# 4) 真实采集 fixture 必须真的采到东西，且含拒绝反例
fx = P('tests/fixtures/lab/live-collection.json')
assert fx.exists(), '缺 live-collection.json（真实 SSH 采集结果）'
d = json.loads(fx.read_text(encoding='utf-8'))
col = d.get('collected') or {}
assert col, 'fixture 里没有采到任何节点——只报失败的话不等于能力可用'
for nid, node in col.items():
    vals = [v for v in (node.get('collected') or {}).values() if v]
    assert vals, f'{nid} 采集项全为空'
errs = ' '.join(d.get('errors') or [])
assert '不猜' in errs, 'fixture 缺「未知型号被拒绝」的反例——只有成功案例证明不了不猜'
""",
    ),
    Gate(
        id='routing-data-is-real',
        desc='路由数据来自真 zebra 而非推断（fixture 含真实路由行且记录了 SYS_ADMIN 依赖）',
        on_fail='block',
        check=r"""
lab = ROOT / 'tests' / 'fixtures' / 'lab'
for n in ('frr-routing-table.txt', 'frr-routing-table-r1.txt'):
    f = lab / n
    assert f.exists(), f'缺路由表 fixture {n}'
    body = f.read_text(encoding='utf-8')
    assert re.search(r'^[KCSOR]>?[*]?\s+\d+\.\d+\.\d+\.\d+', body, re.M), \
        f'{n} 里没有形如「K>* 0.0.0.0/0」的真实路由行——疑似手写样例'
# 采这份数据的关键前提：zebra 需要 SYS_ADMIN，缺了会静默失败。
# 把这个坑记进 fixture，否则下一个接手的人还会踩。
assert 'SYS_ADMIN' in (lab / 'frr-routing-table.txt').read_text(encoding='utf-8'), \
    '路由表 fixture 未记录 zebra 对 SYS_ADMIN 的依赖'
# lab.sh 必须真的声明了这个能力
assert '--cap-add=SYS_ADMIN' in (ROOT / 'scripts' / 'lab.sh').read_text(encoding='utf-8'), \
    'scripts/lab.sh 未声明 --cap-add=SYS_ADMIN，zebra 会静默起不来'
""",
    ),
    Gate(
        id='frontend-has-tests',
        desc='前端不再零测试：存在 npm test 脚本、测试文件，且 App.jsx 真的在用被测模块',
        on_fail='block',
        check=r"""
import json
d = json.loads((ROOT / 'frontend' / 'package.json').read_text(encoding='utf-8'))
assert 'test' in d.get('scripts', {}), 'package.json 无 test 脚本——前端此前零测试，CI 只 build 不 test'
tfiles = [p for p in (ROOT / 'frontend' / 'src').rglob('*.test.js')]
tfiles += [p for p in (ROOT / 'frontend' / 'test').rglob('*.test.mjs')] if (ROOT / 'frontend' / 'test').exists() else []
assert tfiles, '前端无测试文件'
app = (ROOT / 'frontend' / 'src' / 'App.jsx').read_text(encoding='utf-8')
imported = ('./lib/format.js' in app)
assert imported, 'App.jsx 未 import 抽出的模块——测的不是实际运行的那份代码'
for fn in ('compactLabel', 'displayToolName', 'executionLabel', 'localizeJsonText'):
    assert ('function ' + fn) not in app, ('App.jsx 仍保留 ' + fn + ' 的本地副本，抽出的模块等于没接上')
ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
assert 'npm test' in ci, 'CI 未运行前端测试'
""",
    ),
    Gate(
        id='deps-pinned-and-audited',
        desc='依赖全钉版（无 >= / ^ 浮动范围）',
        on_fail='warn',
        check=r"""
import re
LOOSE = ('>=', '<=', '~=', '^')
bad = []
for rel in ('backend/requirements.txt', 'frontend/package.json'):
    for i, line in enumerate((ROOT / rel).read_text(encoding='utf-8').splitlines(), 1):
        for tok in LOOSE:
            if tok in line:
                bad.append(rel + ':' + str(i) + ' ' + line.strip()[:56])
                break
assert not bad, '未钉版本的依赖: ' + '; '.join(bad)
""",
    ),
    Gate(
        id='ci-steps-are-executable',
        desc='CI 里每个可实跑的步骤都真跑一遍（不检查 YAML 长什么样，只检查能不能执行）',
        on_fail='block',
        check=r"""
import sys
sys.path.insert(0, str(ROOT / 'scripts'))
from ci_audit import audit

# 这条门禁是 SBOM 那个 bug 的根治。成因是：我在 CI 里加了 4 个 job，
# 只真跑过 2 个，SBOM 那步写了就再没执行——而我在 CHANGELOG 里写了
# 「supply-chain 全部已修」。写了不跑的 CI 步骤等于没写，还比不写更坏，
# 因为它让人以为覆盖到了。
#
# 所以这里不检查 YAML 长得对不对（文本匹配会命中文档里描述 bug 的那段话），
# 而是把每条命令拿过来真跑一遍。已反验：把 SBOM 换回当初的 -o/-t 写法会被拦下。

res = audit()
assert res['total'] > 0, '没解析出任何 CI 步骤——解析器坏了'
ran = res['ran']
assert ran, '没有任何 CI 步骤被实跑——全被分类跳过了，等于没验'
assert not res['failures'], (
    'CI 步骤实跑失败:\n  ' + '\n  '.join(
        f"{f['job']}/{f['name']} (ci.yml:{f['line']}) 退出码 {f['exit']}\n{f['tail'][-300:]}"
        for f in res['failures']))
""",
    ),
    Gate(
        id='telemetry-not-guessed',
        desc='遥测要么真测（source=real），要么降级且自报 simulated；断链与劣化的判据不得混淆',
        on_fail='block',
        check=r"""
import os, sys
sys.path.insert(0, str(ROOT / 'backend'))
from app.core.telemetry import LOSS_DEGRADED, LOSS_LINK_DOWN
from app.schemas import TelemetrySnapshot
from app.core.telemetry import TELEMETRY

# 1) 断链 vs 劣化的阈值不得混淆。
#    模拟器的拥塞态丢包只有 1.8%，永远落在 5% 以下，所以「5%~90% 该判什么」
#    这条分支在模拟数据下从未被执行过——真实探测一上来就是 120ms+10% 丢包，当场判错。
assert LOSS_LINK_DOWN > LOSS_DEGRADED, '断链阈值必须高于劣化阈值'
s = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.10, throughput_mbps=0.0,
                      alert=True, source='real')
d = TELEMETRY.diagnose([s])
assert d.type == 'congestion', '5%%~90%% 丢包 + 高延迟应为 congestion，实际 %s' % d.type
s2 = TelemetrySnapshot(latency_ms=999.0, packet_loss=1.0, throughput_mbps=0.0,
                       alert=True, source='real')
assert TELEMETRY.diagnose([s2]).type == 'link_down', '近乎全丢才是 link_down'

# 2) 模拟数据的结论必须比真实数据的置信度低，且证据里要标出来源。
real = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=0.0,
                         alert=True, source='real')
fake = TelemetrySnapshot(latency_ms=120.0, packet_loss=0.0, throughput_mbps=0.0,
                         alert=True, source='simulated')
d_real, d_fake = TELEMETRY.diagnose([real]), TELEMETRY.diagnose([fake])
assert d_fake.confidence < d_real.confidence, '模拟数据的置信度必须打折'
assert d_fake.evidence.get('source') == 'simulated', '模拟来源必须出现在证据里'

# 3) 没配探测点时必须降级且如实标注，绝不静默编数
old = os.environ.pop('NETMIND_PROBE_TARGET', None)
try:
    snap = TELEMETRY.sample(record=False)
    assert snap.source == 'simulated', '没有探测点却产出了非 simulated 的快照'
    assert TELEMETRY.provenance()['real'] is False
finally:
    if old is not None:
        os.environ['NETMIND_PROBE_TARGET'] = old
""",
    ),
    Gate(
        id='load-test-no-loss',
        desc='并发压测：零错误 + 压完数据不丢不坏（延迟不设硬阈值，CI 上会抖）',
        on_fail='block',
        check=r"""
import json, re, subprocess, sys
# 延迟基线记录在 docs/load-test-baseline.md。这里只卡「有没有错」和「数据有没有
# 坏」——p99 在 CI runner 上抖动很大，拿它当门禁只会制造假红。性能基线是观察项，
# 不是门禁项。
r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'load_test.py'),
                    '--workers', '8', '--per-worker', '8', '--json'],
                   cwd=ROOT, capture_output=True, text=True, timeout=900)
msg = '压测未通过，退出码 %s；输出尾部: %s %s' % (r.returncode, r.stdout[-600:], r.stderr[-300:])
assert r.returncode == 0, msg
m = re.search(r'\{\s*"scenarios".*\n\}', r.stdout, re.S)
assert m, '压测输出里找不到 JSON 段——报告格式变了'
d = json.loads(m.group(0))
errs = sum(x['errors'] for x in d['scenarios'])
assert errs == 0, f'压测出现 {errs} 类错误'
assert d['data_intact'], '压测后数据文件损坏'
leftover = d['temp_leftovers']
assert leftover == 0, '压测后残留 %d 个临时文件' % leftover
""",
    ),
    Gate(
        id='tests-are-reproducible',
        desc='测试连跑两次结果必须一致（不可复现的测试比没有测试更糟）',
        on_fail='block',
        check=r"""
import re, subprocess, sys
from pathlib import Path as P

# 这条门禁的由来：同一个「未登记 cookie 应被拒绝」的断言，单跑通过、全量失败，
# 再往后又变成「连跑两次结果不同」。三个不同根因都指向同一件事——
# 测试之间/运行之间共享了可变状态：
#   ① data/netmind_store.json 跨运行累积
#   ② importlib.reload(store) 造出新单例，模块间引用指向不同对象
#   ③ STORE 的后台自动保存线程与故障注入的全局替换相撞
# 三条都在 conftest 里治了。治完必须能测出来「真的治好了」。

def _summary(cwd=None, target='backend/tests/'):
    r = subprocess.run([sys.executable, '-m', 'pytest', target, '-q',
                        '--no-header', '-p', 'no:randomly'],
                       cwd=cwd or ROOT, capture_output=True, text=True, timeout=900)
    m = re.search(r'([0-9]+) passed', r.stdout)
    f = re.search(r'([0-9]+) failed', r.stdout)
    return (int(m.group(1)) if m else -1), (int(f.group(1)) if f else 0), r.stdout[-400:]

p1, f1, out1 = _summary()
assert f1 == 0, f'第 1 次全量测试有 {f1} 条失败: {out1}'
p2, f2, out2 = _summary()
assert f2 == 0, f'第 2 次全量测试有 {f2} 条失败——不可复现: {out2}'
assert p1 == p2, f'两次运行通过数不同: {p1} vs {p2}——存在跨运行状态泄漏'

# 还要按 **CI 的方式**再跑一次：ci.yml 的 pytest 步骤是
# `working-directory: backend` + `pytest -q`。上面两次都在仓库根，
# 于是「测试里用了相对路径、换个 cwd 就挂」这类问题这条门禁根本发现不了
# ——实测就是这么漏掉了一个只有从根目录才通过的测试。
# 只在某个 cwd 下通过的测试不是可复现的测试。
p3, f3, out3 = _summary(cwd=(ROOT / 'backend'), target='tests/')
assert f3 == 0, (
    f'按 CI 的方式跑（working-directory=backend）有 {f3} 条失败: {out3}\n'
    f'这类失败通常是测试里用了相对路径——它只在某个 cwd 下通过，不是可复现的。')
assert p3 == p1, f'换 cwd 后通过数不同: 根目录 {p1} vs backend/ {p3}'
""",
    ),
    Gate(
        id='data-durability-drill',
        desc='数据保住：原子写 + 备份/恢复演练必须在 CI 里真跑通',
        on_fail='block',
        check=r"""
import json, subprocess, sys, tempfile, os
from pathlib import Path as P

td = tempfile.mkdtemp(prefix='nm-durability-')
env = dict(os.environ, NETMIND_DATA_FILE=str(P(td) / 'store.json'))
probe = '''
import os, sys
sys.path.insert(0, 'backend')
from app.store import STORE
for i in range(20): STORE.log('durability', 'x'*100, 'info')
assert STORE.save() is True
assert STORE.backup()
'''
r = subprocess.run([sys.executable, '-c', probe], cwd=ROOT, env=env,
                   capture_output=True, text=True, timeout=300)
assert r.returncode == 0, f'造数与备份失败: {r.stderr[-300:]}'

# 跑真实演练：备份 → 破坏 → 恢复 → 校验
r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'data_ops.py'), 'drill'],
                   cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
assert r.returncode == 0, f'恢复演练未通过: {r.stdout[-500:]}{r.stderr[-300:]}'

# 坏恢复源必须被拒——用坏数据盖好数据比不恢复更糟
bad = P(td) / 'bad.json'
bad.write_text('{"broken": ', encoding='utf-8')
r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'data_ops.py'), 'restore', str(bad)],
                   cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
assert r.returncode != 0, '损坏的备份竟被接受了——那会用坏数据盖掉好数据'
r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'data_ops.py'), 'restore', str(P(td)/'nope.json')],
                   cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
assert r.returncode != 0, '不存在的备份竟被接受了'
""",
    ),
    Gate(
        id='state-based-on-is-honest',
        desc='状态文件不得用自指字段冒充当前 HEAD；based_on 必须是真实存在的祖先且不漂太远',
        on_fail='block',
        check=r"""
import json, subprocess
st = json.loads((LOOP_DIR / 'state.json').read_text(encoding='utf-8'))

# 1) 不得再有 head 字段：save() 在提交前跑，它永远指向上一个 commit，
#    叫 head 会让人以为它标识当前状态所在 commit。
assert 'head' not in st, 'state.json 仍有 head 字段——该字段结构上无法自指，会永远差一个 commit'
assert 'based_on' in st, '缺 based_on 字段'

# 2) based_on 必须是真实 commit
sha = st['based_on']
r = subprocess.run(['git', 'cat-file', '-e', sha + '^{commit}'],
                   cwd=ROOT, capture_output=True)
assert r.returncode == 0, f'based_on={sha} 不是仓库里存在的 commit'
r2 = subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'HEAD'],
                    cwd=ROOT, capture_output=True)
assert r2.returncode == 0, f'based_on={sha} 不是当前 HEAD 的祖先'

# 3) 不得漂太远：状态文件是给接手的人看的，差十几个 commit 就过期了
n = int(subprocess.run(['git', 'rev-list', '--count', sha + '..HEAD'],
                       cwd=ROOT, capture_output=True, text=True).stdout.strip() or 0)
assert n <= 3, f'based_on 落后 HEAD {n} 个 commit（>3）——状态快照已过期，接手的人会读到错的状态'

# 4) 字段语义必须写明，否则下个人还是会当 head 读
sem = st.get('_field_semantics') or {}
assert 'based_on' in sem, 'state.json 未记录 based_on 的语义——字段改名却不说理由等于没改'
""",
    ),
    Gate(
        id='sbom-covers-declared-deps',
        desc='CI 的 SBOM 步骤真能跑，且产出的 SBOM 覆盖项目声明的依赖（不是 runner 环境）',
        on_fail='block',
        check=r"""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path as P

# 这条门禁存在的理由：SBOM 步骤写完就再没被执行过。cyclonedx-bom 7.5.0 里
#   -o 是 --output-file（要文件路径，给目录会报 can't open 'x': Is a directory）
#   -t 根本不是合法参数（unrecognized arguments: -t）
# 于是 supply-chain job 一直是红的，只是本地没跑看不出来。
# 而且更糟：那个 job 从不安装 backend/requirements.txt，用 environment 子命令
# 捕获到的是 runner 环境（pip/pip-audit/cyclonedx-bom），**不是项目依赖**——
# 绿的 SBOM 比红的更危险，因为采购会拿它当数。
#
# 修法：不猜命令，直接把 CI YAML 里写的那段真跑一遍，看产物对不对。

ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')

# 1) CI 里必须真装声明依赖，否则 SBOM 抓的是 runner 环境
sbom_block = re.search(r'- name: SBOM\n\s+run: \|\n((?:\s{10,}.*\n)+)', ci)
assert sbom_block, 'CI 里找不到 SBOM 步骤'
block = sbom_block.group(1)
assert 'cyclonedx-py' in block, 'SBOM 步骤没调 cyclonedx-py'
# environment 子命令扫的是已安装环境；本 job 不装项目依赖，用它必然抓错东西
assert 'cyclonedx-py environment' not in block, \
    'SBOM 用 environment 子命令但本 job 未安装 backend/requirements.txt——会抓成 runner 环境'
assert 'requirements' in block, \
    'SBOM 应用 requirements 子命令从声明文件生成，而不是扫环境'

# 2) 把 CI 里写的命令真跑一遍（本地已装 cyclonedx-bom 时）
have_tool = subprocess.run([sys.executable, '-m', 'cyclonedx_py', '--version'],
                           capture_output=True).returncode == 0
if not have_tool:
    import importlib.util
    have_tool = importlib.util.find_spec('cyclonedx') is not None
if have_tool:
    with tempfile.TemporaryDirectory() as td:
        work = P(ROOT / 'backend')
        lines = [c.strip() for c in block.strip().splitlines() if c.strip()
                 and not c.strip().startswith('pip install')]
        assert lines, 'SBOM 步骤里除了 pip install 没别的命令'
        import shlex
        cmd = shlex.split(' '.join(lines))
        # console script 通常与解释器同目录，不在 PATH 上
        exe = P(cmd[0])
        if not exe.exists():
            alt = P(sys.executable).parent / cmd[0]
            if alt.exists():
                cmd[0] = str(alt)
        r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=600)
        out = None
        if '--output-file' in cmd:
            out = work / cmd[cmd.index('--output-file') + 1]
        if out is None or not out.exists():
            cands = sorted(work.glob('*sbom*.json'))
            out = cands[-1] if cands else None
        assert r.returncode == 0, f'CI 的 SBOM 命令实跑失败（退出码 {r.returncode}）: {(r.stderr or r.stdout)[-300:]}'
        assert out is not None, 'SBOM 命令跑通了却没产出文件'
        doc = json.loads(out.read_text(encoding='utf-8'))
        names = {c.get('name') for c in doc.get('components', [])}
        declared = []
        for line in (work / 'requirements.txt').read_text(encoding='utf-8').splitlines():
            line = line.split('#')[0].strip()
            if not line: continue
            declared.append(re.split(r'[=<>!~\[]', line)[0].strip())
        missing = [d for d in declared if d not in names]
        # 跑完清掉产物：它是 CI 的 artifact，不是源码。留着会把工作树弄脏——
        # 与之前「只读命令写盘」同一类副作用，校验工具自己不该留痕。
        if out is not None and out.exists():
            out.unlink()
        assert not missing, f'SBOM 缺声明依赖: {missing}（实际含 {len(names)} 个组件）'
""",
    ),
    Gate(
        id='ci-security-gates',
        desc='CI 具备依赖漏洞扫描（pip-audit / npm audit）',
        on_fail='warn',
        check=r"""
ci = (ROOT / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')
has_pip = 'pip-audit' in ci
has_npm = 'npm audit' in ci
assert has_pip or has_npm, 'CI 无依赖漏洞扫描门（pip-audit / npm audit）'
""",
    ),
    Gate(
        id='dependabot-present',
        desc='依赖自动更新已启用',
        on_fail='warn',
        check=r"""
assert (ROOT / '.github' / 'dependabot.yml').exists(), '无 dependabot/renovate，CVE 响应无自动化'
""",
    ),
]

# ---------------------------------------------------------------- 死模块检测

def _dotted(p: Path) -> str:
    """backend/app/core/audit.py -> app.core.audit"""
    rel = p.relative_to(ROOT / 'backend').with_suffix('')
    parts = list(rel.parts)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def _package_of(p: Path) -> str:
    d = _dotted(p)
    return d.rsplit('.', 1)[0] if '.' in d else ''


def _resolve_relative(importer: Path, level: int, module: str | None) -> str:
    """解析相对导入。importer 是导入方文件，level 是 .. 的个数。"""
    pkg = _package_of(importer).split('.') if _package_of(importer) else []
    up = level - 1
    if up > len(pkg):
        up = len(pkg)
    base = pkg[:len(pkg) - up] if up else pkg
    tail = module.split('.') if module else []
    return '.'.join([*base, *tail])


def _dead_modules() -> list[str]:
    """按导入点索引判定死模块。

    v1 教训（见 state.json retro #1）：曾用 p.stem 做 key、只匹配 ast.ImportFrom.node.module，
    完全漏掉 `from . import audit` 这种形态（module=None，名字在 node.names 里），
    再加上「边扫边移」的级联误判，一次误伤 31 个文件。现改为：
      1) 用完整点分路径做 key，消除 core/audit.py 与 routers/audit.py 的同名碰撞
      2) 覆盖 Import / ImportFrom(含相对层级) / `from . import X` 三种形态
      3) 先建完整索引再判定，扫描期零副作用
      4) 导入证据来自全部 .py（含测试）；只有非测试文件才作为「死」的判定对象
         —— v2 漏了这一条，把「只被测试引用」的模块误判为死
      5) 声明式入口点（pyproject / Dockerfile / compose / CI / README）也算导入证据
    """
    import ast
    backend = ROOT / 'backend'
    all_py = [p for p in sorted(backend.rglob('*.py'))
              if 'node_modules' not in p.parts and '.venv' not in p.parts]
    # 测试文件是 pytest 的发现入口，不是按名导入的模块——不作为「死」的判定对象
    targets = [p for p in all_py
               if not (p.name.startswith('test_') or p.name == 'conftest.py')]
    known = {_dotted(p) for p in all_py}

    imported: set[str] = set()
    for src in all_py:                       # 导入证据来自全部文件，含测试
        try:
            tree = ast.parse(src.read_text(encoding='utf-8', errors='ignore'))
        except Exception:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imported.add(a.name)
                    # import a.b.c 同时也把 a / a.b 视为已引入
                    parts = a.name.split('.')
                    for i in range(1, len(parts)):
                        imported.add('.'.join(parts[:i]))
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    base = _resolve_relative(src, n.level, n.module)
                else:
                    base = n.module or ''
                if base:
                    imported.add(base)
                    parts = base.split('.')
                    for i in range(1, len(parts)):
                        imported.add('.'.join(parts[:i]))
                # `from . import audit` —— 名字本身是被导入的子模块
                for a in n.names:
                    if a.name != '*':
                        imported.add(f'{base}.{a.name}' if base else a.name)

    # 声明式入口点也算导入证据：uvicorn app.main:app / netmind = "app.cli:run"
    declarative = [
        ROOT / 'backend' / 'pyproject.toml',
        ROOT / 'backend' / 'Dockerfile',
        ROOT / 'backend' / 'setup.py',
        ROOT / 'backend' / 'setup.cfg',
        ROOT / 'docker-compose.yml',
        ROOT / '.github' / 'workflows' / 'ci.yml',
        ROOT / 'README.md',
    ]
    for f in declarative:
        if not f.exists():
            continue
        text = f.read_text(encoding='utf-8', errors='ignore')
        for name in known:
            if name and name in text:
                imported.add(name)

    dead = []
    for p in targets:
        if p.name == '__init__.py':
            continue
        name = _dotted(p)
        if name in imported:
            continue
        # 允许「同名子模块 + 唯一 stem 命中」都不算死，但必须有真实导入记录
        dead.append(str(p.relative_to(ROOT)))
    return dead


# ---------------------------------------------------------------- autofix 动作

def fix_move_dead_module() -> tuple[bool, str]:
    """已停用。保留函数名以说明历史：v1 误伤 31 文件后按协议降级为 block。

    任何「删除/移动代码」的动作都需要语义判断，不满足 autofix 的门槛。
    """
    return False, 'autofix 已按协议降级为 block——移动代码需语义判断'


FIXES: dict = {}

# ---------------------------------------------------------------- 执行器


def run_one(gate: Gate) -> tuple[str, str]:
    """返回 (status, detail)；status ∈ pass / fail / skip / error"""
    if gate.check:
        scope = dict(NS)
        scope['LOOP_DIR'] = LOOP_DIR
        # 门禁检查代码可调用本模块的辅助函数（_dead_modules 等）
        scope.update({k: v for k, v in globals().items() if k.startswith('_')})
        try:
            exec(compile(gate.check, f'<gate:{gate.id}>', 'exec'), scope)
            return 'pass', ''
        except AssertionError as exc:
            return 'fail', str(exc) or '断言失败'
        except Exception as exc:
            return 'error', f'{type(exc).__name__}: {exc}'
    if gate.cmd:
        r = subprocess.run(gate.cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
        out = (r.stdout or '') + (r.stderr or '')
        tail = '\n'.join([l for l in out.strip().splitlines() if l.strip()][-6:])
        return ('pass', '') if r.returncode == 0 else ('fail', tail)
    return 'skip', '无检查体'


def run_gates(only: list[str] | None = None, apply_fix: bool = True) -> list[dict]:
    results = []
    for g in GATES:
        if only and g.id not in only:
            continue
        status, detail = run_one(g)
        attempts = 1
        if status == 'fail' and g.on_fail == 'autofix' and apply_fix and g.fix:
            for _ in range(max(0, g.max_attries - 1)):
                fn = FIXES.get(g.fix)
                if not fn:
                    break
                changed, msg = fn()
                if not changed:
                    detail = (detail + f' | autofix 未产生改动: {msg}').strip()
                    break
                status, detail = run_one(g)
                attempts += 1
                if status == 'pass':
                    detail = f'autofix 后通过: {msg}'
                    break
        results.append({
            'id': g.id, 'desc': g.desc, 'on_fail': g.on_fail,
            'status': status, 'detail': detail, 'attempts': attempts,
        })
    return results


def summarize(results: list[dict]) -> tuple[int, int, int]:
    blocking = [r for r in results if r['status'] in ('fail', 'error') and r['on_fail'] in ('block', 'rollback')]
    warned = [r for r in results if r['status'] in ('fail', 'error') and r['on_fail'] == 'warn']
    return sum(1 for r in results if r['status'] == 'pass'), len(results), len(blocking) + len(warned)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', nargs='*', help='只跑指定门禁 id')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--no-fix', action='store_true')
    a = ap.parse_args()
    results = run_gates(a.only, apply_fix=not a.no_fix)
    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = {'pass': 'PASS', 'fail': 'FAIL', 'error': 'ERR ', 'skip': 'SKIP'}[r['status']]
            print(f"  [{mark}] {r['id']:<22} ({r['on_fail']}) {r['desc']}")
            if r['status'] in ('fail', 'error') and r['detail']:
                for line in r['detail'].splitlines():
                    print(f"         {line}")
            elif r['status'] == 'pass' and r['detail']:
                print(f"         {r['detail']}")
    p, t, bad = summarize(results)
    print(f"\n  门禁 {p}/{t} 通过，{bad} 条未通过")
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
