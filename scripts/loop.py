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
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 同 gates.py：循环驱动器会反复调起门禁，绝不能把当前源码状态写进
# __pycache__，否则「注入实验 → 还原」之后会留下加载不掉的幽灵字节码。
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'   # 让子进程也继承
LOOP_DIR = ROOT / '.netmind-loop'
STATE_PATH = LOOP_DIR / 'state.json'
sys.path.insert(0, str(ROOT / 'scripts'))

import gates as gates_mod  # noqa: E402

CST = timezone(timedelta(hours=8))
PRIORITY_ORDER = {'P0': 0, 'P1': 1, 'P2': 2, 'P3': 3}


# ------------------------------------------------------------------ 状态读写

# load() 时刻的磁盘内容指纹。save() 时比对——中间若被别人改过，
# 就拒绝覆盖。这一条是被真实丢更新事件逼出来的：一次 round 要跑三分钟，
# 期间手动或并行写入的 retro 条目会被这进程用自己三分钟前的旧快照整个盖掉，
# 写进去的东西无声消失，人只会以为「保存了」。
_LOADED_DIGEST: str | None = None


def _digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ''


def load() -> dict:
    global _LOADED_DIGEST
    _LOADED_DIGEST = _digest(STATE_PATH)
    return json.loads(STATE_PATH.read_text(encoding='utf-8'))


def save(st: dict) -> None:
    global _LOADED_DIGEST
    if _LOADED_DIGEST is not None and _digest(STATE_PATH) != _LOADED_DIGEST:
        raise SystemExit(
            '⛔ 拒绝落盘：state.json 在本进程读取之后被改过。\n'
            '   本进程持有的是旧快照，直接写会把别人的改动无声覆盖。\n'
            '   请重新运行本命令；若确认要放弃他人改动，先 git checkout 状态文件。')
    # 字段名是 based_on 不是 head：save() 发生在提交**之前**，所以这里记下的
    # HEAD 永远是「本状态基于哪个 commit 写下的」，不可能是「包含本状态的
    # 那个 commit」——那是自指的，结构上做不到。叫 head 会让人以为它标识
    # 当前状态所在 commit，实际总是差一个。
    st['updated'] = datetime.now(CST).isoformat(timespec='seconds')
    st['based_on'] = subprocess.run(
        ['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
        capture_output=True, text=True).stdout.strip()
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _LOADED_DIGEST = _digest(STATE_PATH)


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
        'tests_collected': count_tests(),
        'src_lines': line_count(ROOT, ('*.py', '*.mjs', '*.ts', '*.jsx', '*.css')),
        'generic_names': generic,
        'dead_modules': dead,
        'slop_hits': slop,
        'license_present': (ROOT / 'LICENSE').exists(),
    }


def count_tests() -> int:
    """真实用例数，用 pytest 自己的收集结果。

    此前数的是 `def test_` 的定义个数——parametrize 会把一个函数展开成多个用例
    （test_driver_mapping 里一个 parametrize 展开 6 个），静态计数会少报。
    而且这个指标叫 tests_passed，静态计数既不是「用例数」也不是「通过数」，
    名实不符会让趋势线失真。改用 pytest --collect-only 的权威结果。
    """
    r = subprocess.run(
        [sys.executable, '-m', 'pytest', str(ROOT / 'backend' / 'tests'),
         '--collect-only', '-q', '--no-header'],
        capture_output=True, text=True, timeout=600, cwd=ROOT)
    m = re.search(r'(\d+)\s+tests? collected', r.stdout)
    if m:
        return int(m.group(1))
    # 收集失败时退回静态计数，但要在指标里区分得出来
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
    """跑门禁并打印。不落盘——查状态不该改状态。

    门禁计数写进 state.metrics 的动作留给 `round` 与显式的 `metrics`，
    否则「看一眼门禁」会把已提交的 state.json 弄脏，而脏的是别人下次接手
    时读到的第一份文件。
    """
    print('\n  跑门禁：')
    results = gates_mod.run_gates()
    for r in results:
        mark = {'pass': 'PASS', 'fail': 'FAIL', 'error': 'ERR ', 'skip': 'SKIP'}[r['status']]
        print(f"  [{mark}] {r['id']:<30} ({r['on_fail']}) {r['desc']}")
        if r['status'] in ('fail', 'error') and r['detail']:
            for line in r['detail'].splitlines()[:5]:
                print(f'         {line}')
    p, t, bad = gates_mod.summarize(results)
    print(f'\n  门禁 {p}/{t} 通过，{bad} 条未通过')
    return 0 if bad == 0 else 1


def cmd_metrics(st: dict) -> int:
    st['metrics'].update(compute_metrics())
    # 两个字段都写。只写顶层会让 metrics 停在上一次的值（曾长期显示 15 而实际 16），
    # 只写 metrics 则顶层那份给旧读取方的兼容字段是旧的——顶层对不代表 metrics 对。
    st['metrics']['gates_total'] = len(gates_mod.GATES)
    st['gates_total'] = len(gates_mod.GATES)
    # 成员关系不需要跑门禁也知道；状态保持原样（没跑过就是没跑过）
    sync_gate_membership(st)
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
    # 空轮守卫：协议要求「每轮产出可验证的增量」。
    # 不用工作树有无改动来判——修文档、补 retro 也会产生 diff，但那是上一轮的事；
    # 而且暂存不等于本轮产出。改为硬性要求 BUILD 阶段声明 deliverable。
    if not str(cr.get('deliverable', '')).strip():
        print('\n  ⛔ 拒绝落盘：本轮未声明 deliverable')
        print('     门禁全绿不等于有产出——修文档/补 retro 也能让门禁变绿，但那是上一轮的事。')
        print('     请在 state.json 的 current_round.deliverable 写明本轮实际交付了什么；')
        print('     确为空轮收尾就如实写「无产出」并说明原因，别记成正常轮次。')
        return 1
    st['cycle'] += 1
    st['metrics'].update(compute_metrics())
    st['metric_history'].append({'cycle': st['cycle'], **st['metrics']})
    st['rounds'].append({
        'cycle': st['cycle'], 'id': cr['id'], 'title': cr['title'],
        'shipped': cr.get('deliverable', ''), 'at': datetime.now(CST).isoformat(timespec='seconds'),
        'based_on': st.get('based_on'),
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


def sync_gate_membership(st: dict) -> None:
    """让 `st['gates']` 的成员与 gates.py 里的实际门禁一致。

    成员关系是**不跑门禁也知道**的：gates.py 里有什么，这里就该有什么。
    状态不是——只有真跑过才有，所以新进来的门禁先记 'not-run'，
    宁可显式写「没跑过」，也别让它看起来跑过且通过了。
    """
    by_id = {g.id: g for g in gates_mod.GATES}
    known = {g['id']: g for g in st['gates']}
    merged = []
    for gid, g in by_id.items():
        prev = known.get(gid)
        merged.append({
            'id': gid,
            'on_fail': g.on_fail,
            'status': (prev or {}).get('status', 'not-run'),
        })
    st['gates'] = merged


def record_gate_results(st: dict, results: list) -> None:
    """把一轮门禁结果记进 state。**唯一**的记账入口。

    此前这段逻辑在 `cmd_round` 里抄了一份、`cmd_metrics` 里又抄了一份，
    两份各自漂移：round 那份只更新顶层 `gates_total`（漏了 metrics 里的同一个
    字段），且只按 id 更新 `st['gates']` 里**已有**的条目，从不追加新门禁。
    结果状态文件长期长这样：顶层 gates_total=54（对）、
    metrics.gates_total=22（八轮前的旧值）、st['gates'] 只有最早的 8 条。
    一个以「自己的数字必须诚实」为立身之本的工具，状态文件里的数字是假的，
    而没有任何门禁在管这件事。

    复制粘贴式记账的真正代价不是写错一行，是**下次加门禁时你不知道该改哪一处**。
    """
    p, _total, _bad = gates_mod.summarize(results)
    total = len(gates_mod.GATES)
    # 两个字段都写。只写顶层会让 metrics 停在旧值——顶层那份是给旧读取方
    # 的兼容字段，它对不代表 metrics 对。
    st['gates_total'] = total
    st['metrics']['gates_total'] = total
    st['metrics']['gates_passed'] = p
    st['metrics']['gates_warned'] = sum(
        1 for r in results if r['status'] != 'pass' and r['on_fail'] == 'warn')
    by_id = {r['id']: r for r in results}
    sync_gate_membership(st)
    for gid, r in by_id.items():
        for g in st['gates']:
            if g['id'] == gid:
                g['status'] = r['status']
                g['on_fail'] = r['on_fail']      # 退路也可能是后来改的
                break


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
    record_gate_results(st, results)
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
    # 只读命令不落盘：查一眼状态就把已提交的 state.json 弄脏，是很难发现的
    # 副作用——下次接手的人读到的第一份文件就被改过。status/gates 只读；
    # metrics 是显式的刷新命令，plan/state/round/retro/block 会改状态。
    READ_ONLY = {'status', 'gates'}
    rc = {'status': cmd_status, 'gates': cmd_gates, 'metrics': cmd_metrics,
          'plan': cmd_plan, 'state': cmd_state, 'round': cmd_round,
          'save': lambda s: (save(s), print('  state.json 已保存'), 0)[2]}[a.cmd](st)
    if a.cmd not in READ_ONLY:
        save(st)
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
