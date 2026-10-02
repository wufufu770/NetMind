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
