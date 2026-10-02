"""驱动映射的回归。

这些用例的存在理由：此前的映射表内联在 _collect_live 里，把 Linux/FRR 设备
映射到 napalm 根本不存在的 'linux' 驱动，并把任何未知 kind 静默兜底成 'eos'。
napalm 5.2 核心实测只带 eos/junos/ios/iosxr/nxos/nxos_ssh 六个驱动，
表里的 'nokia' 与 'srl' 分属未声明的插件。

映射错了不会静默通过——它会对着错误型号发命令，这比报错严重。
"""
import importlib.util

import pytest

from app.diagnose.drivers import (CORE_DRIVERS, KIND_TO_DRIVER, PLUGIN_DRIVERS,
                                  driver_available, pick_driver)

# napalm / netmiko 在 requirements-drivers.txt 里，不在 requirements.txt。
# CI 只装 requirements.txt，所以依赖驱动的用例必须显式跳过而不是失败——
# 否则 CI 红的是一个「本机装了驱动」的环境差异，不是代码问题。
NAPALM_PRESENT = importlib.util.find_spec('napalm') is not None
requires_napalm = pytest.mark.skipif(
    not NAPALM_PRESENT,
    reason='需可选驱动依赖（pip install -r backend/requirements-drivers.txt）；CI 未安装，故跳过')


def test_linux_and_frr_are_explicitly_unsupported():
    """Linux/FRR 不是 napalm 能驱的型号。曾经的兜底 'linux' 永远不存在，
    必然抛 ModuleImportError——而错误信息会被当成「设备连不上」。"""
    for kind in ('linux', 'alpine', 'frr', 'debian', 'ubuntu', 'busybox'):
        name, reason = pick_driver(kind)
        assert name is None, f'{kind} 不该被映射到 {name}'
        assert 'napalm' in reason, f'{kind} 应归入「Linux 系 napalm 驱不了」而非「未识别」: {reason}'


def test_unknown_kind_is_never_guessed_as_eos():
    """把未知设备当 Arista EOS 去发命令，比直接报错危险得多。"""
    for kind in ('vyos', 'mikrotik', 'huawei', ' Paloalto', 'typo-kind', ''):
        name, reason = pick_driver(kind)
        assert name != 'eos', f'{kind!r} 被静默兜底成 eos'
        if name is None:
            assert reason, '拒绝映射时必须给出原因'


def test_known_kinds_map_to_real_drivers():
    assert pick_driver('ceos')[0] == 'eos'
    assert pick_driver('vr-vmx')[0] == 'junos'
    assert pick_driver('crpd')[0] == 'junos'
    assert pick_driver('vr-sros')[0] == 'nokia'
    assert pick_driver('srl')[0] == 'srl'


def test_every_mapped_driver_is_core_or_declared_plugin():
    """映射表里的每个驱动，要么是 napalm 核心自带，要么有对应插件声明。
    此前 nokia / srl 两者皆无——在声明的依赖下永远不可能成功。"""
    for kind, drv in KIND_TO_DRIVER.items():
        assert drv in CORE_DRIVERS or drv in PLUGIN_DRIVERS, \
            f'{kind}→{drv} 既非核心驱动也无插件声明'


def test_plugin_drivers_are_declared_as_optional_extras():
    """插件必须在 requirements-drivers.txt 里以 optional 形式出现，
    否则映射表里的两项是永远走不通的死路。"""
    from pathlib import Path
    txt = (Path(__file__).resolve().parents[2] / 'backend' / 'requirements-drivers.txt').read_text(encoding='utf-8')
    for drv, pkg in PLUGIN_DRIVERS.items():
        assert pkg in txt, f'{pkg} 未在 requirements-drivers.txt 声明，{drv} 驱动永远不可用'


@requires_napalm
@pytest.mark.parametrize('drv', sorted(CORE_DRIVERS))
def test_core_drivers_really_import(drv):
    """核心驱动必须真的可用——映射表不能凭空列。"""
    ok, why = driver_available(drv)
    assert ok, f'{drv} 声称是核心驱动却不可用: {why}'


def test_bogus_driver_reports_unavailable_not_raises():
    ok, why = driver_available('definitely-not-a-driver')
    assert ok is False
    assert why, '不可用时必须说明原因'
