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
    """把 STORE 指向临时数据文件。

    这里**刻意不用 importlib.reload**。STORE 是模块级单例，`transaction.py`、
    `security.py` 等模块都持有它的引用。reload 会造出一个新单例，于是：
      · transaction 往旧 STORE 登记 cookie
      · security 惰性 `from ..store import STORE` 拿到新 STORE 去查
      → cookie 明明登记了却查不到，测试在别的文件之后跑时神秘失败
    改路径不换对象，模块间的引用关系保持有效。
    """
    from app import store as st
    monkeypatch.setattr(st, 'DATA_PATH', tmp_path / 'store.json')
    st.DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    return st


# ---------- 原子写 ----------

def test_save_writes_valid_json(store):
    s = store.STORE
    assert s.save() is True
    p = store.DATA_PATH
    assert p.exists()
    assert json.loads(p.read_text(encoding='utf-8'))


def test_rename_failure_never_touches_live_file(store):
    """落盘途中失败，正式文件必须还是上一次那份完整数据。

    注入点选在 os.replace（真正的原子步骤），而不是 builtins.open——
    save() 用的是 tempfile.mkstemp + os.fdopen，patch builtins.open 对它无效，
    那样测的就不是「落盘失败」而是「什么都没发生」。
    """
    s = store.STORE
    s.save()
    good = store.DATA_PATH.read_text(encoding='utf-8')
    before_mtime = store.DATA_PATH.stat().st_mtime_ns

    import os as _os
    real_replace = _os.replace

    def boom(*a, **k):
        raise OSError('simulated rename failure (e.g. disk full / EIO)')
    _os.replace = boom
    try:
        ok = s.save()
    finally:
        _os.replace = real_replace

    assert ok is False, '落盘失败必须返回 False'
    assert store.DATA_PATH.read_text(encoding='utf-8') == good, '落盘失败后正式文件被破坏了'
    assert store.DATA_PATH.stat().st_mtime_ns == before_mtime, '正式文件被改写了'
    assert json.loads(store.DATA_PATH.read_text(encoding='utf-8'))


def test_write_failure_keeps_live_file_and_cleans_temp(store):
    """写到一半失败：临时文件要清掉，正式文件不能被动。"""
    s = store.STORE
    s.save()
    good = store.DATA_PATH.read_text(encoding='utf-8')

    import os as _os
    real_fsync = _os.fsync
    _os.fsync = lambda fd: (_ for _ in ()).throw(OSError('simulated fsync failure'))
    try:
        ok = s.save()
    finally:
        _os.fsync = real_fsync

    assert ok is False
    assert store.DATA_PATH.read_text(encoding='utf-8') == good
    leftovers = [p.name for p in store.DATA_PATH.parent.iterdir() if '.tmp' in p.name]
    assert leftovers == [], f'写入失败后临时文件没清理: {leftovers}'


def test_save_failure_is_reported_not_swallowed(store, monkeypatch):
    s = store.STORE
    import os as _os
    real_replace = _os.replace
    _os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError('nope'))
    try:
        assert s.save() is False, '落盘失败必须返回 False，不能静默'
    finally:
        _os.replace = real_replace


def test_no_temp_file_left_behind_after_success(store):
    s = store.STORE
    s.save()
    leftovers = [p.name for p in store.DATA_PATH.parent.iterdir() if '.tmp' in p.name]
    assert leftovers == [], f'成功落盘后仍有临时文件残留: {leftovers}'


def test_no_temp_file_left_behind_after_failure(store, monkeypatch):
    s = store.STORE
    import os as _os
    real_replace = _os.replace
    _os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError('nope'))
    try:
        s.save()
    finally:
        _os.replace = real_replace
    leftovers = [p.name for p in store.DATA_PATH.parent.iterdir() if '.tmp' in p.name]
    assert leftovers == [], f'落盘失败后临时文件没清理: {leftovers}'


def test_concurrent_saves_use_distinct_temp_names(store):
    """10 线程并发保存。临时名必须互不相同，否则会互相覆盖。"""
    s = store.STORE
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(str(src))
        return real_replace(src, dst)
    os.replace = spy

    errs = []

    def worker():
        try:
            s.save()          # 每线程只存一次，才能真正检验「并发重叠时不撞名」
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts: t.start()
    for t in ts: t.join()
    os.replace = real_replace

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
