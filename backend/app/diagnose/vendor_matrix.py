"""厂商能力矩阵。

原��「多厂商」只存在于 README 的一句描述和 drivers.py 的映射表里，两者都可能
与实态漂移——之前就漂移过：映射表列了 nokia/srl 但依赖里没声明插件。

这里把「支持哪些厂商」变成**可核查的矩阵**，且每条都标清验证等级：

  verified  —— 已在真实设备/容器上跑通采集，见 tests/fixtures/lab/
  declared  —— 映射与依赖都齐备，逻辑可走通，但未在真实设备上验过
  blocked   —— 缺驱动插件或缺设备，明确标出卡在哪

对外的诚实表只引用本模块，不再自己复述——避免两处口径漂移。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from .drivers import CORE_DRIVERS, PLUGIN_DRIVERS, driver_available

VERIFIED = 'verified'
DECLARED = 'declared'
BLOCKED = 'blocked'


@dataclass(frozen=True)
class Vendor:
    name: str
    kinds: tuple[str, ...]
    transport: str          # napalm / netmiko
    driver: str
    level: str
    note: str = ''


VENDORS: tuple[Vendor, ...] = (
    # —— 已在真实容器上跑通采集 ——
    Vendor('linux/frr', ('linux', 'alpine', 'debian', 'frr'), 'netmiko', 'linux', VERIFIED,
           '实验室拓扑的主力设备类型；tests/fixtures/lab/live-collection.json 为真实采集结果'),
    # —— napalm 核心驱动，映射与依赖齐备 ——
    Vendor('arista-eos', ('ceos', 'eos', 'arista'), 'napalm', 'eos', DECLARED,
           'napalm 核心自带 eos 驱动；未在真实 ceos 设备上验过'),
    Vendor('juniper-junos', ('vr-vmx', 'junos', 'crpd', 'vjunosswitch'), 'napalm', 'junos', DECLARED,
           'napalm 核心自带 junos；crpd 实为 containerlab 的 routing daemon 而非 Juniper 设备，'
           '映射到 junos 只是「类 Junos 语法」的近似，未在真实 Juniper 设备上验过'),
    Vendor('cisco-ios', ('ios', 'iosxe', 'cat9k'), 'napalm', 'ios', DECLARED,
           'napalm 核心自带 ios；未在真实设备上验过'),
    Vendor('cisco-nxos', ('nxos', 'nxos_ssh'), 'napalm', 'nxos', DECLARED,
           'napalm 核心自带 nxos；未在真实设备上验过'),
    Vendor('cisco-iosxr', ('iosxr',), 'napalm', 'iosxr', DECLARED,
           'napalm 核心自带 iosxr；未在真实设备上验过'),
    # —— 映射列了但依赖未声明/插件未装 ——
    Vendor('nokia-sros', ('vr-sros',), 'napalm', 'nokia', BLOCKED,
           '需 napalm-nokia 插件（已登记为可选 extras，未装）'),
    Vendor('nokia-srl', ('srl',), 'napalm', 'srl', BLOCKED,
           '需 napalm-srl 插件（已登记为可选 extras，未装）'),
)


def matrix() -> list[dict]:
    """导出矩阵。blocked 判定是实时的——插件装了会自动升为 declared。"""
    rows = []
    for v in VENDORS:
        level = v.level
        note = v.note
        if v.transport == 'napalm' and v.driver in PLUGIN_DRIVERS:
            ok, why = driver_available(v.driver)
            if ok and level == BLOCKED:
                level, note = DECLARED, f'插件已装，映射可用；{note}'
        rows.append({**asdict(v), 'level': level, 'note': note,
                     'kinds': list(v.kinds)})
    return rows


def summary() -> dict:
    rows = matrix()
    return {
        'total': len(rows),
        VERIFIED: sum(1 for r in rows if r['level'] == VERIFIED),
        DECLARED: sum(1 for r in rows if r['level'] == DECLARED),
        BLOCKED: sum(1 for r in rows if r['level'] == BLOCKED),
        'napalm_core_drivers': sorted(CORE_DRIVERS),
    }


def as_markdown() -> str:
    """渲染成可直接贴进文档的表。列固定，不随内容伸缩。"""
    s = summary()
    lines = [
        '| 厂商 | containerlab kind | 传输 | 驱动 | 验证等级 | 说明 |',
        '|---|---|---|---|---|---|',
    ]
    for r in matrix():
        lines.append('| {name} | {kinds} | {transport} | `{driver}` | **{level}** | {note} |'.format(
            name=r['name'], kinds=' / '.join(r['kinds']), transport=r['transport'],
            driver=r['driver'], level=r['level'], note=r['note']))
    lines.append('')
    lines.append(f"共 {s['total']} 家：已验证 {s[VERIFIED]} · 声明齐备未验 {s[DECLARED]} · 阻塞 {s[BLOCKED]}。"
                 f"napalm 核心驱动：{', '.join(s['napalm_core_drivers'])}")
    return '\n'.join(lines)
