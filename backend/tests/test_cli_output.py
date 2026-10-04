"""CLI 的输出契约。

CLI 是一层薄适配器，但它是对用户说话的那一层。「沉默」在那层是最贵的：
命令退出 0、stdout 全空，使用者无法区分「失败了」和「确实没有数据」。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.cli import format_log_line


def test_log_line_uses_standard_format():
    line = format_log_line({'ts': '2026-10-04T10:00:00Z', 'level': 'warn',
                             'source': 'driver', 'message': 'timeout'})
    assert line == '2026-10-04T10:00:00Z [warn] driver: timeout'


def test_log_line_survives_legacy_rows_missing_fields():
    """持久化的旧记录可能缺字段——`row['x']` 会 KeyError 让 CLI 崩掉。"""
    for row in ({}, {'ts': 'x'}, {'message': 'm'}, {'source': ''}, {'level': None}):
        line = format_log_line(row)
        assert isinstance(line, str) and line.strip(), f'格式化失败: {row} → {line!r}'


def test_log_line_does_not_invent_a_source():
    """来源缺失时写「来源未标注」，不替它编一个 system。

    与前端 display.js 的 provenanceLabel 同一套口径——两边各编一次的话，
    同一份数据在 CLI 与界面上会显示成不同的来源。
    """
    assert '来源未标注' in format_log_line({'ts': 't', 'level': 'info', 'message': 'm'})
    assert '来源未标注' not in format_log_line({'ts': 't', 'source': 'real',
                                                'level': 'info', 'message': 'm'})


def test_empty_log_list_is_announced(tmp_path, monkeypatch):
    """空结果必须说一声，而不是退出 0 且什么都不打印。"""
    import app.cli as cli_mod
    from typer.testing import CliRunner

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr(cli_mod, '_get', lambda *a, **k: [])
    runner = CliRunner()
    res = runner.invoke(cli_mod.app, ['logs', '--limit', '3'])
    assert res.exit_code == 0
    assert res.stdout.strip(), '空结果时 stdout 为空——使用者无法区分失败与无数据'
    assert '没有匹配' in res.stdout
