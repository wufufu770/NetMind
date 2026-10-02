#!/usr/bin/env python3
"""无限迭代循环驱动器。

五个阶段：BUILD → TEST → IMPROVE → PLAN → STATE（落盘）。
详见 .netmind-loop/protocol.md。

    python3 scripts/loop.py status
    python3 scripts/loop.py gates
    python3 scripts/loop.py metrics
    python3 scripts/loop.py plan
    python3 scripts/loop.py state
    python3 scripts/loop.py round
"""
from __future__ import annotations

import argparse

import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOP_DIR = ROOT / '.netmind-loop'
STATE_PATH = LOOP_DIR / 'state.json'
sys.path.insert(0, str(ROOT / 'scripts'))

import gates as gates_mod  # noqa: E402

CST = timezone(timedelta(hours=8))
PRIORITY_ORDER = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}


# ------------------------------------------------------------------ 状态读写

def load() -> dict:
    return json.loads(STATE_PATH.read_text(encoding='utf-8'))


def save(st: dict) -> None:
    st['updated'] = datetime.now(CST).isoformat(timespec='seconds')
    st['head'] = subprocess.run(
        ['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


# ------------------------------------------------------------------ 指标

def compute_metrics() -> dict:
    def line_count(base: Path, globs: tuple[str, ...]) -> int:
        total = 0
        for g in globs:
            for p in base.rglob(g):
                if '.git' in p.parts or 'node_modules' in p.parts or '.venv' in p.parts:
                    continue
                try:
                    total += len(p.read_text(encoding='utf-8', errors='ignore').splitlines())
                except Exception:
                    pass
        return total

    app = ROOT / 'backend' / 'app'
    generic = 0
    for p in app.rglob('*.py'):
        generic += len(re.findall(
            r'\b(?:data|items|values|result|value|obj|tmp|manager)\b',
            p.read_text(encoding='utf-8', errors='ignore')))

    # 死模块数必须与门禁同源——否则指标会与门禁结论打架
    try:
        dead = len(gates_mod._dead_modules())
    except Exception:
        dead = -1

    slop = 0
    lint = ROOT / 'scripts' / 'copy_lint.py'
    if lint.exists():
        r = subprocess.run([sys.executable, str(lint)], cwd=ROOT, capture_output=True, text=True)
        m = re.search(r'AI 味命中 (\d+) 项', r.stdout or '')
        slop = int(m.group(1)) if m else 0

    return {
        'tests_passed': count_tests(),
        'src_lines': line_count(ROOT, ('*.py', '*.mjs', '*.ts', '*.jsx', '*.css')),
        'generic_names': generic,
        'dead_modules': dead,
        'slop_hits': slop,
        'license_present': (ROOT / 'LICENSE').exists(),
    }


def count_tests() -> int:
    n = 0
    tdir = ROOT / 'backend' / 'tests'
    if tdir.exists():
        for p in tdir.glob('test_*.py'):
            n += len(re.findall(r'^\s*(?:async )?def test_', p.read_text(encoding='utf-8'), re.M))
    return n


# ------------------------------------------------------------------ 各阶段

def cmd_status(st: dict) -> int:
    print(f'\n  NetMind 循环 · 第 {st["cycle"]} 轮已完成 · 阶段 {st["phase"]}')
    cr = st.get('current_round')
    if cr:
        print(f'  当前轮次: {cr["id"]} — {cr["title"]}')
    print('\n  指标:')
    for k, v in st['metrics'].items():
        print(f'    {k:<20} {v}')
    mh = st.get('metric_history') or []
    if mh:
        print('\n  趋势:')
        keys = sorted({k for h in mh for k in h if k != 'cycle'})
        for h in mh:
            cells = ' '.join(f'{k}={h.get(k)}' for k in keys)
            print(f'    轮{h["cycle"]}: {cells}')
    nxt = st.get('next_round') or pick_next(st)
    blocked = sum(1 for b in st['backlog'] if b['status'] == 'blocked')
    if nxt:
        prio = nxt.get('priority', '')
        line = f'{nxt["id"]} — {nxt["title"]}' + (f'  [{prio}]' if prio else '')
    else:
        line = '（backlog 空，plan 将自动补货）'
    print(f'\n  下一轮: {line}')
    print(f'  待办 {sum(1 for b in st["backlog"] if b["status"] == "pending")} 条 · '
          f'阻塞 {blocked} 条 · 推迟 {len(st.get("deferred", []))} 条 · retro {len(st.get("retro", []))} 条')
    return 0


def cmd_gates(st: dict) -> int:
    print('\n  跑门禁：')
    for r in gates_mod.run_gates():
        mark = {'pass': 'PASS', 'fail': 'FAIL', 'error': 'ERR ', 'skip': 'SKIP'}[r['status']]
        print(f"  [{mark}] {r['id']:<22} ({r['on_fail']}) {r['desc']}")
        if r['status'] in ('fail', 'error') and r['detail']:
            for line in r['detail'].splitlines()[:6]:
                print(f'         {line}')
    p, t, bad = gates_mod.summarize(gates_mod.run_gates())
    print(f'\n  门禁 {p}/{t} 通过，{bad} 条未通过')
    st['metrics']['gates_passed'] = p
    st['metrics']['gates_total'] = t
    return 0 if bad == 0 else 1


def cmd_metrics(st: dict) -> int:
    st['metrics'].update(compute_metrics())
    st['gates_total'] = len(gates_mod.GATES)
    print('\n  指标已刷新：')
    for k, v in st['metrics'].items():
        print(f'    {k:<20} {v}')
    return 0


def pick_next(st: dict) -> dict | None:
    """选下一轮：按 priority + 依赖，跳过 blocked。

    `status: blocked` 的待办必须有 `blocked_on` 字段说明卡在谁/什么上。
    这是实际使用暴露的缺口——v1 只会按优先级选，结果选中一个卡在法务审阅上的
    P0，整个循环就停在那里，而 backlog 里明明还有一堆能做��� P1/P2。
    """
    done = {r['id'] for r in st['rounds']}
    done |= {b['id'] for b in st['backlog'] if b['status'] == 'done'}
    # 当前轮在 STATE 阶段才标 done，而 PLAN 跑在 STATE 之前——必须显式排除，
    # 否则「下一轮」会选中本轮正在做的同一项
    cur = (st.get('current_round') or {}).get('id')
    if cur:
        done.add(cur)
    pending = [b for b in st['backlog']
               if b['status'] == 'pending'
               and not b.get('blocked_on')]
    ready = [b for b in pending
             if all(d in done or any(x['id'] == d and x['status'] == 'done' for x in st['backlog'])
                    for d in b.get('depends_on', []))]
    pool = ready or pending
    if not pool:
        return None
    return sorted(pool, key=lambda b: (PRIORITY_ORDER.get(b['priority'], 9), b['id']))[0]


def cmd_block(st: dict, argv: list[str]) -> int:
    """把一条待办标为外部阻塞。"""
    if not argv:
        print('  用法: loop.py block <backlog-id> "<卡在什么上>"')
        return 1
    bid, reason = argv[0], (argv[1] if len(argv) > 1 else '未说明')
    hit = False
    for b in st['backlog']:
        if b['id'] == bid:
            b['status'] = 'blocked'
            b['blocked_on'] = reason
            hit = True
            break
    if not hit:
        print(f'  ⚠ backlog 中无 {bid}')
        return 1
    print(f'  {bid} 已标 blocked：{reason}')
    return 0


def replenish_backlog(st: dict) -> str:
    """backlog 空时按协议补货：先捞 deferred，再固化连续失败门禁。"""
    if st['backlog']:
        return 'backlog 非空'
    added = []
    for d in st.get('deferred', []):
        st['backlog'].append({
            'id': d['id'], 'title': d['title'], 'priority': 'P2',
            'depends_on': [], 'status': 'pending',
            'note': f'从 deferred 捞回：{d["reason"][:60]}',
        })
        added.append(d['id'])
    if not added:
        metrics = st.get('metrics', {})
        st['backlog'].append({
            'id': 'AUTO-metric-regression', 'title': '指标停滞排查（协议自动生成）',
            'priority': 'P2', 'depends_on': [], 'status': 'pending',
            'note': f'backlog 空且 deferred 也空。指标快照: {metrics}',
        })
        added.append('AUTO-metric-regression')
    return f'自动补货: {", ".join(added)}'


def cmd_plan(st: dict) -> int:
    note = replenish_backlog(st)
    nxt = pick_next(st)
    if nxt is None:
        print('  ⚠ 无可用待办，且补货失败——需人工介入')
        return 1
    st['next_round'] = {
        'id': nxt['id'], 'title': nxt['title'],
        'why': nxt.get('note', ''), 'deliverable': '',
        'planned_at': datetime.now(CST).isoformat(timespec='seconds'),
    }
    st['phase'] = 'build'
    print(f'\n  {note}')
    print(f'  下一轮: {nxt["id"]} — {nxt["title"]}  [{nxt["priority"]}]')
    if nxt.get('depends_on'):
        print(f'    依赖: {", ".join(nxt["depends_on"])}')
    return 0


def cmd_state(st: dict) -> int:
    """落盘：轮次 +1，进指标历史，本轮待办标 done。

    注意 current_round 与 next_round 必须分开：PLAN 阶段只写 next_round，
    否则 STATE 会把「刚规划好的下一轮」误标成「本轮已完成」。
    这是 v1 真实踩过的坑，见 state.json retro #3。
    """
    cr = st.get('current_round')
    if not cr:
        print('  ⚠ 无 current_round，无法落盘——先跑 plan')
        return 1
    st['cycle'] += 1
    st['metrics'].update(compute_metrics())
    st['metric_history'].append({'cycle': st['cycle'], **st['metrics']})
    st['rounds'].append({
        'cycle': st['cycle'], 'id': cr['id'], 'title': cr['title'],
        'shipped': cr.get('deliverable', ''), 'at': datetime.now(CST).isoformat(timespec='seconds'),
        'head': st['head'],
    })
    hit = False
    for b in st['backlog']:
        if b['id'] == cr['id']:
            b['status'] = 'done'
            hit = True
    if not hit:
        st['backlog'].append({
            'id': cr['id'], 'title': cr['title'], 'priority': 'P1',
            'depends_on': [], 'status': 'done',
            'note': '本轮由 plan 直接指定，未预先登记在 backlog',
        })
    st['phase'] = 'plan'
    st['current_round'] = None
    print(f'\n  第 {st["cycle"]} 轮已落盘')
    for r in st['rounds'][-3:]:
        print(f'    轮{r["cycle"]}  {r["id"]}  {r["title"][:44]}')
    return 0


def cmd_retro(st: dict, argv: list[str]) -> int:
    """显式记入根因。

    自动捕获只能记「门禁红了」，记不住「为什么这个门禁当初会写错」。
    事故类根因必须显式登记，否则同一个错误的设计会被重犯。
    """
    if not argv:
        print('  用法: loop.py retro <gate-or-area> "<根因>" "<修法>"')
        return 1
    area = argv[0]
    cause = argv[1] if len(argv) > 1 else '未填'
    fix = argv[2] if len(argv) > 2 else '未填'
    st.setdefault('retro', []).append({
        'cycle': st['cycle'] + 1, 'gate': area, 'on_fail': 'manual',
        'root_cause': cause, 'fix': fix,
        'at': datetime.now(CST).isoformat(timespec='seconds'),
    })
    print(f'  已记入 retro: {area}')
    return 0


def promote_next(st: dict) -> bool:
    """BUILD 入口：把 next_round 提升为 current_round。

    v1 只有 plan 写 next_round、state 读 current_round，中间少了提升这一步，
    于是跑完一轮后 current_round 为空，state 拒绝落盘。
    """
    if st.get('current_round'):
        return False
    nxt = st.get('next_round')
    if not nxt:
        return False
    st['current_round'] = dict(nxt)
    return True


def cmd_round(st: dict) -> int:
    if promote_next(st):
        st['phase'] = 'build'
        print(f"\n══ BUILD ══\n  本轮: {st['current_round']['id']} — {st['current_round']['title']}")
    print('\n══ TEST ══')
    results = gates_mod.run_gates()
    for r in results:
        mark = {'pass': 'PASS', 'fail': 'FAIL', 'error': 'ERR ', 'skip': 'SKIP'}[r['status']]
        print(f"  [{mark}] {r['id']:<22} ({r['on_fail']}) {r['desc']}")
        if r['status'] in ('fail', 'error') and r['detail']:
            for line in r['detail'].splitlines()[:5]:
                print(f'         {line}')
    st['gates_total'] = len(gates_mod.GATES)
    p, t, bad = gates_mod.summarize(results)
    st['metrics']['gates_passed'] = p
    st['metrics']['gates_warned'] = sum(1 for r in results if r['status'] != 'pass' and r['on_fail'] == 'warn')
    for g in st['gates']:
        match = next((r for r in results if r['id'] == g['id']), None)
        if match:
            g['status'] = match['status']
    st['phase'] = 'test'

    print('\n══ IMPROVE ══')
    new_retro = [r for r in results if r['status'] in ('fail', 'error')]
    if new_retro:
        for r in new_retro:
            st['retro'].append({
                'cycle': st['cycle'] + 1, 'gate': r['id'], 'on_fail': r['on_fail'],
                'root_cause': r['detail'][:400] or '未记录',
                'fix': '待定——本轮不记根因的门禁会原样复现',
                'at': datetime.now(CST).isoformat(timespec='seconds'),
            })
        print(f'  记入 {len(new_retro)} 条根因（fix 字段待人工补全，这是纪律要求）')
    else:
        print('  门禁全通过，无需记根因')

    if bad:
        blocking = [r for r in new_retro if r['on_fail'] in ('block', 'rollback')]
        if blocking:
            print(f'\n  ⛔ {len(blocking)} 条阻断级门禁未过，本轮不予落盘')
            for r in blocking:
                print(f'     {r["id"]}: {r["detail"][:120]}')
            return 1

    print('\n══ PLAN ══')
    cmd_plan(st)
    print('\n══ STATE ══')
    return cmd_state(st)


def main() -> int:
    ap = argparse.ArgumentParser(description='NetMind 无限迭代循环驱动器')
    ap.add_argument('cmd', choices=['status', 'gates', 'metrics', 'plan', 'state', 'round', 'save', 'retro', 'block'])
    ap.add_argument('rest', nargs='*', help='retro 的参数: <area> <根因> <修法>')
    a = ap.parse_args()
    st = load()
    if a.cmd == 'retro':
        rc = cmd_retro(st, a.rest)
        save(st)
        return rc
    if a.cmd == 'block':
        rc = cmd_block(st, a.rest)
        save(st)
        return rc
    rc = {'status': cmd_status, 'gates': cmd_gates, 'metrics': cmd_metrics,
          'plan': cmd_plan, 'state': cmd_state, 'round': cmd_round,
          'save': lambda s: (save(s), print('  state.json 已保存'), 0)[2]}[a.cmd](st)
    if a.cmd != 'save':
        save(st)
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
