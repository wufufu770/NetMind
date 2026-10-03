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

GATES: list[Gate] = [
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

    rep = TELEMETRY.heal(Diagnosis(type='anomaly_traffic', confidence=0.9),
                         iface='eth0', rate_mbps=5)
    assert calls['deploy'] == 1, '前置条件不成立：deploy 没被调用'
    assert calls['rollback'] == 1, \
        '下发成功但指标没改善，却没有触发回滚——坏变更被留在设备上了'
    assert rep.success is False, '没改善却报成功'

    rb = rep.improvement.get('rollback')
    assert rb and rb.get('attempted') is True, '报告里没有回滚记录，无法判断是否撤销过'
    assert rb.get('capability') == ROLLBACK_INVERSE, \
        f"anomaly_traffic 是可逆的，回滚能力不该报成 {rb.get('capability')}"

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

def _summary():
    r = subprocess.run([sys.executable, '-m', 'pytest', 'backend/tests/', '-q',
                        '--no-header', '-p', 'no:randomly'],
                       cwd=ROOT, capture_output=True, text=True, timeout=900)
    m = re.search(r'([0-9]+) passed', r.stdout)
    f = re.search(r'([0-9]+) failed', r.stdout)
    return (int(m.group(1)) if m else -1), (int(f.group(1)) if f else 0), r.stdout[-300:]

p1, f1, out1 = _summary()
assert f1 == 0, f'第 1 次全量测试有 {f1} 条失败: {out1}'
p2, f2, out2 = _summary()
assert f2 == 0, f'第 2 次全量测试有 {f2} 条失败——不可复现: {out2}'
assert p1 == p2, f'两次运行通过数不同: {p1} vs {p2}——存在跨运行状态泄漏'
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
