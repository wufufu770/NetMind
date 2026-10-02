"""从 ci.yml 抽出所有 run 块并实跑，校验每个 CI 步骤真能执行。

为什么需要它：我在 Round 1 往 CI 加了 4 个 job，只真跑过 2 个。SBOM 那一步写了
就再没执行过——`cyclonedx-py ... -o frontend -t python` 在 7.5.0 下退出码 2，
而我却在 CHANGELOG 里写了「supply-chain 全部已修」。**写了不跑的 CI 步骤等于
没写，而且比不写更坏：它让人以为覆盖到了。**

更糟的是那个 job 从不安装 backend/requirements.txt，用 environment 子命令扫的
是 runner 环境，产出的 SBOM 里没有任何项目依赖——绿的假数据比红的坏数据危险。

所以本模块不检查 YAML 长什么样，而是把每条命令**拿过来真跑一遍**。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / '.github' / 'workflows' / 'ci.yml'

# 装依赖的动作不在这里跑（会改环境、耗时长），但它们的存在本身要校验
INSTALL_RE = re.compile(r'^\s*(pip|npm|apt|apk)\s+(install|ci)\b')
# 明显只能在 CI 里跑的动作（需要 runner 的特定状态）
CI_ONLY_MARKERS = ('${{', 'actions/', 'git checkout', 'gh ')


@dataclass
class Step:
    job: str
    name: str
    run: str
    workdir: str
    lineno: int


def _line_of(text: str, name: str) -> int:
    for i, l in enumerate(text.splitlines(), 1):
        if l.strip().startswith('- name:') and name in l:
            return i
    return 0


def parse_steps(text: str) -> list[Step]:
    """用 PyYAML 真解析，不用正则手撸。

    手撸版本只认出块标量 `run: |`，内联的 `run: pytest -q` 全漏——那正是
    最该跑的步骤。PyYAML 在 requirements.txt 里，用它没有额外依赖成本。
    """
    import yaml
    doc = yaml.safe_load(text) or {}
    steps: list[Step] = []
    for job_name, job in (doc.get('jobs') or {}).items():
        if not isinstance(job, dict):
            continue
        for st in (job.get('steps') or []):
            if not isinstance(st, dict) or 'run' not in st:
                continue
            run = st.get('run')
            if not isinstance(run, str):
                continue
            wd = st.get('working-directory', '')
            nm = str(st.get('name') or '(未命名)')
            steps.append(Step(job_name, nm, run.strip(), str(wd or ''), _line_of(text, nm)))
    return steps


def split_commands(run: str) -> list[str]:
    """把一个 run 块拆成逻辑命令。

    `npm ci --no-audit --no-fund && npm test` 是一个 run 块里两件事：装依赖 + 跑测试。
    只看首个 token 的话整块被归为 install，真正该验的 `npm test` 就被跳过了。
    这里按行与 && 拆开，装依赖的丢掉，剩下的才是「这一步真正在验什么」。
    """
    cmds = []
    for line in run.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        for part in line.split('&&'):
            part = part.strip()
            if part:
                cmds.append(part)
    return cmds


def classify(step: Step) -> str:
    if not step.run:
        return 'empty'
    if any(m in step.run for m in CI_ONLY_MARKERS):
        return 'ci-only'
    cmds = split_commands(step.run)
    if not cmds:
        return 'empty'
    if all(INSTALL_RE.match(c) for c in cmds):
        return 'install'
    if all(INSTALL_RE.match(c) for c in cmds[:1]) and len(cmds) > 1:
        return 'mixed'          # 装依赖 + 验东西，只验后半截
    return 'runnable'


def exec_targets(step: Step) -> list[str]:
    """这一步真正要验的命令（去掉装依赖的那些）。"""
    return [c for c in split_commands(step.run) if not INSTALL_RE.match(c)]


def run_step(step: Step) -> tuple[int, str]:
    workdir = ROOT if step.workdir in ('', '.') else ROOT / step.workdir
    if not workdir.exists():
        return -1, f'working-directory 不存在: {step.workdir}'
    cmds = exec_targets(step)
    if not cmds:
        return 0, ''
    # CI 靠 actions/setup-python 把解释器与 console script 放上 PATH；本地要自己补，
    # 否则会误报成「命令找不到」，把真失败淹没在环境差异里。
    env = dict(os.environ)
    bindir = str(Path(sys.executable).parent)
    env['PATH'] = bindir + os.pathsep + env.get('PATH', '')
    out = ''
    for c in cmds:
        r = subprocess.run(['bash', '-c', c], cwd=workdir, env=env,
                           capture_output=True, text=True, timeout=1200)
        out += ((r.stdout or '') + (r.stderr or ''))[-400:]
        if r.returncode != 0:
            return r.returncode, f'$ {c}\n' + out
    return 0, out


def audit(run_heavy: bool = True) -> dict:
    text = CI_YML.read_text(encoding='utf-8')
    steps = parse_steps(text)
    buckets: dict[str, list[Step]] = {}
    for s in steps:
        buckets.setdefault(classify(s), []).append(s)
    result = {'total': len(steps), 'buckets': {k: len(v) for k, v in buckets.items()},
              'ran': [], 'skipped': [], 'failures': []}
    for s in steps:
        kind = classify(s)
        # loop-gates 那一步是门禁执行器自身。在门禁里再跑它 = 门禁 → 审计 → 门禁，
        # 无限递归。它验的东西由本审计的其余步骤 + 门禁本身覆盖，直接跳过。
        if s.job == 'loop-gates':
            result['skipped'].append({'job': s.job, 'name': s.name,
                                      'kind': 'self-recursive', 'line': s.lineno})
            continue
        if kind in ('empty', 'ci-only', 'install'):
            result['skipped'].append({'job': s.job, 'name': s.name, 'kind': kind, 'line': s.lineno})
            continue
        if not run_heavy:
            result['skipped'].append({'job': s.job, 'name': s.name, 'kind': kind, 'line': s.lineno})
            continue
        code, out = run_step(s)
        if code == 0:
            result['ran'].append({'job': s.job, 'name': s.name, 'line': s.lineno})
        else:
            result['failures'].append({'job': s.job, 'name': s.name, 'line': s.lineno,
                                      'exit': code, 'tail': out})
    return result


def main() -> int:
    res = audit()
    print(f"CI 步骤共 {res['total']} 条 · 分类 {res['buckets']}")
    print(f"  实跑通过 {len(res['ran'])}：")
    for r in res['ran']:
        print(f"    ✅ {r['job']}/{r['name']} (ci.yml:{r['line']})")
    print(f"  按类别跳过 {len(res['skipped'])}（install / ci-only / 空）：")
    for r in res['skipped']:
        print(f"    · {r['job']}/{r['name']} [{r['kind']}] (ci.yml:{r['line']})")
    if res['failures']:
        print(f"  ✗ 实跑失败 {len(res['failures'])}：")
        for r in res['failures']:
            print(f"    ❌ {r['job']}/{r['name']} (ci.yml:{r['line']}) 退出码 {r['exit']}")
            for line in r['tail'].splitlines()[-5:]:
                print(f"         {line}")
        return 1
    print('\n  所有可实跑的 CI 步骤均通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
