"""CLI 新增命令的输出契约。

`netmind vendors` 第一版把字段写成 `verification`，而真实响应里是 `level` ——
结果「验证等级」整列显示成 `-`，而那一列恰恰是这张表唯一要说的事：
只有 verified 的那家在真机上跑通过，其余是映射齐备但未验。
**一列全是 `-` 的表比没有这张表更糟**，它看起来像「没有等级信息」，
实际是「我没读对字段」。
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import app.cli as cli_mod
from typer.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


def _stub(monkeypatch, payload):
    monkeypatch.setattr(cli_mod, '_get', lambda *a, **k: payload)


VENDORS = {
    'summary': {'verified': 1, 'declared': 5, 'blocked': 2},
    'vendors': [
        {'name': 'linux/frr', 'kinds': ['linux', 'frr'], 'transport': 'netmiko',
         'driver': 'linux', 'level': 'verified', 'note': '真实采集结果'},
        {'name': 'cisco-ios', 'kinds': ['ios'], 'transport': 'napalm',
         'driver': 'ios', 'level': 'declared', 'note': ''},
    ],
}


def test_vendors_shows_the_real_verification_level(runner, monkeypatch):
    _stub(monkeypatch, VENDORS)
    res = runner.invoke(cli_mod.app, ['vendors'])
    assert res.exit_code == 0
    # 断言必须落在**表格行**上，不能扫全文：汇总行里有 {"verified": 1}，
    # 扫全文的话字段名写错也能蒙混过关——第一版就是这么废掉的。
    row = next((l for l in res.stdout.splitlines() if 'linux/frr' in l and '│' in l), '')
    assert row, '厂商表格里没有 linux/frr 这一行'
    assert 'verified' in row, f'验证等级列没显示出来——字段名读错了？该行: {row}'
    assert '-' not in row.split('│')[-2], f'验证等级列是空的: {row}'
    cisco = next((l for l in res.stdout.splitlines() if 'cisco-ios' in l and '│' in l), '')
    assert 'declared' in cisco, f'第二行也没读到等级: {cisco}'
    assert 'linux,frr' in res.stdout.replace(' ', ''), '型号（kinds）没显示'


def test_vendors_does_not_render_a_column_of_dashes(runner, monkeypatch):
    """整列都是 `-` 说明字段没读到，而不是「没有等级信息」。"""
    _stub(monkeypatch, VENDORS)
    res = runner.invoke(cli_mod.app, ['vendors'])
    lines = [l for l in res.stdout.splitlines() if '│' in l and 'linux/frr' in l]
    assert lines, '厂商表格里没有 linux/frr 这一行'
    assert lines[0].count('-') < 3, f'该行有多处空缺，疑似字段没读到: {lines[0]}'


def test_vendors_shows_note(runner, monkeypatch):
    _stub(monkeypatch, VENDORS)
    res = runner.invoke(cli_mod.app, ['vendors'])
    assert '真实采集结果' in res.stdout


def test_notifications_empty_is_announced(runner, monkeypatch):
    _stub(monkeypatch, [])
    res = runner.invoke(cli_mod.app, ['notifications'])
    assert res.exit_code == 0
    assert res.stdout.strip(), '空告警列表不得零输出'


def test_notifications_prints_rows(runner, monkeypatch):
    _stub(monkeypatch, [{'level': 'warn', 'source': 'telemetry', 'message': '超时'}])
    res = runner.invoke(cli_mod.app, ['notifications'])
    assert '超时' in res.stdout and 'telemetry' in res.stdout


def test_readiness_passes_through(runner, monkeypatch):
    _stub(monkeypatch, {'ready': True, 'missing': [], 'rules': 35,
                        'agents': 9, 'tools': 24, 'store_path': '/app/data/s.json'})
    res = runner.invoke(cli_mod.app, ['readiness'])
    assert res.exit_code == 0
    assert 'ready' in res.stdout and 'rules' in res.stdout
