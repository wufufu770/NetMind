"""厂商矩阵的回归。

这条存在的理由：项目一直宣称「多厂商」，但「多厂商」只存在于 README 的一句
描述和 drivers.py 的映射表里——两者都可能与实态漂移，之前就漂移过（映射列了
nokia/srl 而依赖里没声明插件）。

矩阵必须能从代码导出，且自带验证等级；README 不得自己复述一份。
"""
import json

from app.diagnose.drivers import PLUGIN_DRIVERS, pick_driver
from app.diagnose.vendor_matrix import (BLOCKED, DECLARED, VERIFIED, VENDORS,
                                        as_markdown, matrix, summary)


def test_every_vendor_declares_a_verification_level():
    for v in VENDORS:
        assert v.level in (VERIFIED, DECLARED, BLOCKED), f'{v.name} 等级非法: {v.level}'
        assert v.note, f'{v.name} 必须说明为什么是这个等级'


def test_verified_vendors_must_have_real_fixture_backing():
    """"已验证"不能是自封的——必须有真实采集 fixture 支撑。"""
    from pathlib import Path
    fx = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'lab' / 'live-collection.json'
    if not fx.exists():
        verified = [v for v in VENDORS if v.level == VERIFIED]
        assert not verified, '声明为 verified 但没有 live-collection.json 支撑'
        return
    d = json.loads(fx.read_text(encoding='utf-8'))
    col = d.get('collected') or {}
    assert col, 'fixture 存在但没采到任何节点'
    transport = {n.get('transport', '') for n in col.values()}
    # fixture 里记的是 'netmiko/linux' 这种带细节的串，按前缀匹配
    for v in VENDORS:
        if v.level == VERIFIED:
            assert any(t.startswith(v.transport) for t in transport), \
                f'{v.name} 标 verified 但 fixture 里没有对应的真实采集记录（现有: {transport}）'


def test_every_vendor_kind_maps_to_its_declared_driver():
    """矩阵里写的 kind 必须真的映射到矩阵里写的驱动——两处不能各说各话。"""
    for v in VENDORS:
        if v.transport != 'napalm':
            continue
        for kind in v.kinds:
            name, reason = pick_driver(kind)
            assert name == v.driver, \
                f'{v.name} 矩阵写驱动 {v.driver}，但 pick_driver({kind}) 给的是 {name}（{reason}）'


def test_blocked_vendors_declare_their_plugin():
    for v in VENDORS:
        if v.level == BLOCKED and v.transport == 'napalm':
            assert v.driver in PLUGIN_DRIVERS, \
                f'{v.name} 标 blocked 但未声明对应插件 {PLUGIN_DRIVERS.get(v.driver)}'


def test_summary_counts_add_up():
    s = summary()
    assert s[VERIFIED] + s[DECLARED] + s[BLOCKED] == s['total'], '等级计数与总数不符'


def test_matrix_is_json_serialisable():
    json.dumps(matrix(), ensure_ascii=False)


def test_markdown_renders_all_rows_with_levels():
    md = as_markdown()
    for v in VENDORS:
        assert v.name in md, f'{v.name} 未出现在 markdown 里'
        assert f'**{v.level}**' in md, f'{v.name} 的等级未标出'
    assert '已验证' in md and '阻塞' in md


def test_readme_points_at_matrix_instead_of_restating_vendors():
    """README 不得自己复述一份厂商表——两处口径必然漂移。只允许引用。"""
    from pathlib import Path
    readme = (Path(__file__).resolve().parents[2] / 'README.md').read_text(encoding='utf-8')
    assert 'diagnose/vendor_matrix.py' in readme or '/api/vendors' in readme, \
        'README 未引用厂商矩阵——它自己那套说法会与实态漂移'
