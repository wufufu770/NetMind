#!/usr/bin/env python3
"""「客户可见文档」的唯一口径。

为什么值得单独成文件：这个项目已经被**手写文档清单**坑过三次了，而且三次
是同一个错——

  · `security-doc-matches-behavior` 当初修 SECURITY.md 时才想起来把
    `docs/*.md` 加进清单，于是 `CONTRIBUTING.md` / `CLA.md` /
    `.netmind-loop/protocol.md` 各漏一份。实测往 CONTRIBUTING.md 塞回那句
    错话，门禁照样绿。
  · `no-missing-as-zero` 只盯 `App.jsx`，而渲染逻辑早就抽进
    `frontend/src/lib/` 了。实测往 `lib/charts.js` 放一个
    `m.latency_ms || 0`，照样绿。
  · `copy_lint.py` 的 `CUSTOMER_FACING` 又是一份手写清单，同样在漏。

共同点不是「某一处忘了」，而是**清单会随代码/文档搬家而腐烂，且没有任何
东西会提醒谁回来补**。所以口径只写这一份：谁需要谁 import，不许再抄第二遍。

「客户可见」的判定用 git 而不是目录结构——被 git 跟踪（含新增未提交、
未被 ignore 的）就是会发布出去的那批文件。这样新增文档自动入网。
非 git 环境（打包下载的源码包）退回按目录扫，并且**照样断言确实扫到了
东西**：扫描范围静默退化成零，比不设门禁更坏。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 按目录扫时的排除项：生成物与第三方。都不该参与「客户可见」判定。
_SKIP_PARTS = {
    'node_modules', '__pycache__', '.pytest_cache',
    'dist', 'build', 'data', 'venv',
}


def customer_facing(root: Path | None = None) -> list[Path]:
    """返回所有客户可见 Markdown 的绝对路径（已排序、不存在的已剔除）。"""
    root = root or ROOT
    try:
        out = subprocess.run(
            ['git', '-C', str(root), 'ls-files', '-z',
             '--cached', '--others', '--exclude-standard', '*.md'],
            capture_output=True, text=True, timeout=30, check=True).stdout
        paths = [root / f for f in out.split('\0') if f]
    except (subprocess.SubprocessError, OSError):
        paths = sorted(
            p for p in root.rglob('*.md')
            if not (_SKIP_PARTS & set(p.relative_to(root).parts)))
    found = [p for p in paths if p.exists()]
    if not found:
        raise AssertionError(
            '一份客户可见文档都没扫到——扫描范围退化了，'
            '这条检查会永远放行，恰恰是它最不该有的行为')
    return sorted(found)


if __name__ == '__main__':
    for p in customer_facing():
        print(p.relative_to(ROOT))
