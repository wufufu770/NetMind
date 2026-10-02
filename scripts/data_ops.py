#!/usr/bin/env python3
"""NetMind 数据保全命令：备份 / 恢复 / 自检 / 演练。

商业部署里最怕的是「升级到一半才发现数据没了」。这三个命令是那时的救命绳：

  backup              打一份带时间戳的备份
  backup --to PATH    打到指定位置
  restore FILE        从备份恢复（备份坏了会拒绝，不会用坏数据盖好的）
  verify              校验当前数据文件是否完整可解析
  drill               演练：备份 → 破坏 → 恢复 → 校验
  list                列出可用备份

用法：
  python3 scripts/data_ops.py backup
  python3 scripts/data_ops.py restore data/netmind_store.backup-20261003-010635.json
  python3 scripts/data_ops.py drill
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def _store():
    from app.store import STORE, DATA_PATH
    return STORE, DATA_PATH


def cmd_backup(a) -> int:
    STORE, DATA_PATH = _store()
    if not DATA_PATH.exists():
        print(f'  数据文件不存在，无可备份: {DATA_PATH}')
        return 1
    target = Path(a.to) if a.to else None
    path = STORE.backup(target)
    size = Path(path).stat().st_size
    print(f'  ✅ 已备份 → {path}  ({size} 字节)')
    return 0


def cmd_restore(a) -> int:
    STORE, DATA_PATH = _store()
    src = Path(a.file)
    try:
        res = STORE.restore_from(src)
    except Exception as exc:
        print(f'  ❌ 拒绝恢复: {type(exc).__name__}: {exc}')
        print('     恢复前请确认备份文件本身是好的——用坏备份覆盖好数据比不恢复更糟')
        return 1
    print(f'  ✅ 已从 {src} 恢复（{res["keys"]} 个顶层键）→ {DATA_PATH}')
    return 0


def cmd_seed(a) -> int:
    """造一批数据并落盘——演练与本地验证的前置。"""
    STORE, DATA_PATH = _store()
    for i in range(a.count):
        STORE.log('seed', f'entry-{i} ' + 'x' * 100, 'info')
    ok = STORE.save()
    print(f'  已写入 {a.count} 条日志，save()={ok} → {DATA_PATH} ({DATA_PATH.stat().st_size} 字节)')
    return 0 if ok else 1


def cmd_verify(a) -> int:
    STORE, DATA_PATH = _store()
    if not DATA_PATH.exists():
        print(f'  数据文件不存在: {DATA_PATH}')
        return 1
    try:
        data = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        print(f'  ❌ 数据文件已损坏: {exc}')
        return 1
    n = {k: len(v) if isinstance(v, (list, dict)) else 1 for k, v in data.items()}
    print(f'  ✅ 数据文件完好，{DATA_PATH.stat().st_size} 字节')
    print('     内容:', ', '.join(f'{k}={v}' for k, v in sorted(n.items())))
    return 0


def cmd_list(a) -> int:
    STORE, DATA_PATH = _store()
    backups = sorted(DATA_PATH.parent.glob(f'{DATA_PATH.stem}.backup-*{DATA_PATH.suffix}'))
    if not backups:
        print(f'  {DATA_PATH.parent} 下没有备份')
        return 0
    for p in backups:
        print(f'  {p.stat().st_size:>10} 字节  {p}')
    print(f'\n  共 {len(backups)} 份')
    return 0


def cmd_drill(a) -> int:
    """恢复演练。备份 → 破坏 → 恢复 → 校验。演练通过才敢在真出事时用。"""
    STORE, DATA_PATH = _store()
    if not DATA_PATH.exists():
        print(f'  无数据文件可演练（{DATA_PATH}）；先启动一次服务让 STORE 落盘')
        return 1
    print('  ① 备份')
    bk = Path(STORE.backup())
    original = DATA_PATH.read_text(encoding='utf-8')
    print(f'     → {bk.name}')

    print('  ② 破坏当前数据文件')
    DATA_PATH.write_text('{"corrupted": ', encoding='utf-8')
    try:
        json.loads(DATA_PATH.read_text(encoding='utf-8'))
        print('     ⚠ 破坏后竟然能解析，演练环境有问题')
        return 1
    except json.JSONDecodeError:
        print('     ✓ 已损坏且可被检出')

    print('  ③ 从备份恢复')
    STORE.restore_from(bk)
    print('     ✓ 已恢复')

    print('  ④ 校验')
    rc = cmd_verify(a)
    same = DATA_PATH.read_text(encoding='utf-8') == original
    print(f'  ⑤ 与破坏前内容一致: {same}')
    if rc != 0 or not same:
        return 1
    print('\n  ✅ 恢复演练通过——真出事时这套流程是可用的')
    bk.unlink(missing_ok=True)
    print('     （演练用的备份已删除）')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='NetMind 数据保全')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('backup', help='备份')
    p.add_argument('--to', help='目标路径（默认按时间戳命名）')
    p.set_defaults(fn=cmd_backup)

    p = sub.add_parser('restore', help='从备份恢复')
    p.add_argument('file', help='备份文件路径')
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser('seed', help='造测试数据并落盘')
    p.add_argument('--count', type=int, default=20)
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser('verify', help='校验当前数据文件')
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser('list', help='列出可用备份')
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser('drill', help='恢复演练：备份→破坏→恢复→校验')
    p.set_defaults(fn=cmd_drill)

    a = ap.parse_args()
    print(f'  数据文件: {os.getenv("NETMIND_DATA_FILE", "(默认路径)")}')
    return a.fn(a)


if __name__ == '__main__':
    raise SystemExit(main())
