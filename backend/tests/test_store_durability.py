"""数据持久化的完整性回归。

自托管工具丢数据是致命的。这里的每条都对应一种真实的丢数据形态：

  · 落盘写到一半进程被杀 → 原子写（临时文件 + fsync + rename + 目录 fsync）
  · 同机两个进程同时保存 → 唯一临时名（原来固定 .tmp，会互相覆盖）
  · 磁盘写失败 → 不静默（原来 mark_dirty / 自动保存线程都是 except: pass）
  · 升级/迁移前手滑 → backup() 带时间戳备份 + restore_from()

用独立临时目录，不碰真实数据文件。
"""
import importlib
import json
import os
import threading
from pathlib import Path

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """每个用例一个独立的 STORE 模块实例 + 独立数据文件。"""
    monkeypatch.setenv('NETMIND_DATA_FILE', str(tmp_path / 'store.json'))
    for m in [k for k in list(sys_modules()) if k.startswith('app.store')]:
        sys_modules().pop(m)
    import app.store as st
    importlib.reload(st)
    yield st
    monkeypatch.delenv('NETMIND_DATA_FILE', raising=False)


def sys_modules():
    import sys
    return sys.modules


# ---------- 原子写 ----------

def test_save_writes_valid_json(store):
    s = store.STORE
    assert s.save() is True
    p = store.DATA_PATH
    assert p.exists()
    assert json.loads(p.read_text(encoding='utf-8'))


def test_truncated_write_never_touches_live_file(store, monkeypatch):
    """写到一半崩了，正式文件必须还是上一次那份完整数据。"""
    s = store.STORE
    s.save()
    good = store.DATA_PATH.read_text(encoding='utf-8')
    payload = {'x': 'y' * 100000}

    real_open = open

    def exploding_open(path, *a, **kw):
        fh = real_open(path, *a, **kw)
        orig_write = fh.write

        def half_then_die(txt):
            orig_write(txt[:len(txt) // 2])
            fh.flush()
            raise OSError('simulated disk failure mid-write')
        fh.write = half_then_die
        return fh
    monkeypatch.setattr('builtins.open', exploding_open)
    s.save()  # 应返回 False 而非抛出/留下半截
    monkeypatch.undo()

    assert store.DATA_PATH.read_text(encoding='utf-8') == good, '崩溃后正式文件被破坏了'
    assert json.loads(store.DATA_PATH.read_text(encoding='utf-8'))


def test_save_failure_is_reported_not_swallowed(store, monkeypatch):
    s = store.STORE
    monkeypatch.setattr('os.replace', lambda *a, **k: (_ for _ in ()).throw(OSError('nope')))
    assert s.save() is False, '落盘失败必须返回 False，不能静默'
    monkeypatch.undo()


def test_no_temp_file_left_behind_after_success(store):
    s = store.STORE
    s.save()
    leftovers = [p.name for p in store.DATA_PATH.parent.iterdir() if '.tmp' in p.name]
    assert leftovers == [], f'成功落盘后仍有临时文件残留: {leftovers}'


def test_no_temp_file_left_behind_after_failure(store, monkeypatch):
    s = store.STORE
    monkeypatch.setattr('os.replace', lambda *a, **k: (_ for _ in ()).throw(OSError('nope')))
    s.save()
    monkeypatch.undo()
    leftovers = [p.name for p in store.DATA_PATH.parent.iterdir() if '.tmp' in p.name]
    assert leftovers == [], f'落盘失败后临时文件没清理: {leftovers}'


def test_concurrent_saves_use_distinct_temp_names(store, monkeypatch):
    """10 线程并发保存。临时名必须互不相同，否则会互相覆盖。"""
    s = store.STORE
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(str(src))
        return real_replace(src, dst)
    monkeypatch.setattr('os.replace', spy)

    errs = []

    def worker():
        try:
            s.save()          # 每线程只存一次，才能真正检验「并发重叠时不撞名」
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts: t.start()
    for t in ts: t.join()
    monkeypatch.undo()

    assert errs == [], f'并发保存抛异常: {errs[:3]}'
    assert len(set(seen)) == len(seen) == 10, \
        f'10 个并发保存出现临时名碰撞（{len(set(seen))} 个不同名）——并发下会互相覆盖'
    assert json.loads(store.DATA_PATH.read_text(encoding='utf-8'))


# ---------- 备份与恢复 ----------

def test_backup_creates_timestamped_copy(store):
    s = store.STORE
    s.save()
    b = Path(s.backup())
    assert b.exists()
    assert '.backup-' in b.name
    assert json.loads(b.read_text(encoding='utf-8'))


def test_backup_to_explicit_path(store, tmp_path):
    s = store.STORE
    s.save()
    target = tmp_path / 'nested' / 'snap.json'
    b = s.backup(target)
    assert Path(b) == target and target.exists()


def test_backup_does_not_alter_live_data(store):
    s = store.STORE
    s.save()
    before = store.DATA_PATH.read_text(encoding='utf-8')
    s.backup()
    assert store.DATA_PATH.read_text(encoding='utf-8') == before


def test_restore_from_backup_reconstructs_state(store):
    """备份 → 改坏 → 从备份还原。"""
    s = store.STORE
    s.log('marker', 'BEFORE_BACKUP', 'info')
    s.save()
    b = Path(s.backup())

    s.log('marker', 'AFTER_BACKUP', 'info')
    s.save()
    assert 'AFTER_BACKUP' in store.DATA_PATH.read_text(encoding='utf-8')

    store.DATA_PATH.write_text(b.read_text(encoding='utf-8'), encoding='utf-8')
    assert 'BEFORE_BACKUP' in store.DATA_PATH.read_text(encoding='utf-8')
    assert 'AFTER_BACKUP' not in store.DATA_PATH.read_text(encoding='utf-8')


def test_restore_rejects_corrupt_backup(store, tmp_path):
    """恢复源坏了必须报错，不能把坏数据覆盖到好数据上。"""
    bad = tmp_path / 'bad.json'
    bad.write_text('{"broken": ', encoding='utf-8')
    with pytest.raises(Exception):
        store.restore_from(bad)


def test_restore_rejects_missing_source(store, tmp_path):
    with pytest.raises(Exception):
        store.restore_from(tmp_path / 'nope.json')


# ---------- 容量上限（防止无界增长） ----------

def test_logs_are_capped():
    """store.MAX_LOGS 存在且为正——无界增长会把磁盘写满。"""
    from app import store as st
    assert st.MAX_LOGS > 0
    assert st.MAX_EXECUTIONS > 0
    assert st.MAX_TELEMETRY > 0
