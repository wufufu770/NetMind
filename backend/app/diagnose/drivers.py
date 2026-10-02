"""设备类型 → 采集驱动的映射。

此前这段逻辑内联在 engine._collect_live 里，映射表有五项、兜底有两支，全部有问题：

  1. 映射到 napalm 并不存在的驱动——实测 napalm 5.2 核心只带
     eos / junos / ios / iosxr / nxos / nxos_ssh 六个。表里的 'nokia' 与 'srl'
     分属 napalm-nokia / napalm-srl 插件，而 requirements-drivers.txt 从未声明它们，
     所以这两项在声明的依赖下永远不可能成功。
  2. 兜底分支 `'linux' if 'linux' in kind else 'eos'`：napalm 根本没有 linux 驱动，
     于是所有 linux/FRR 设备都必然抛 ModuleImportError；而任何**未知** kind 会被
     静默当成 Arista EOS——对着错误型号发命令，比直接报错更危险。
  3. ModuleImportError 被塞进 errors 列表，和「设备不可达」长得一样，调用方
     分不清「这型号不支持」与「这台设备连不上」。

改成显式映射 + 显式不支持，并把插件依赖作为可选 extras 写进 requirements。
"""
from __future__ import annotations

# kind（containerlab 里的 kind）→ napalm 驱动名。只列实测可用的。
KIND_TO_DRIVER = {
    'ceos': 'eos',
    'arista': 'eos',
    'eos': 'eos',
    'vr-vmx': 'junos',
    'junos': 'junos',
    'crpd': 'junos',
    'vjunosswitch': 'junos',
    'vr-sros': 'nokia',      # 需 napalm-nokia 插件，见 PLUGIN_DRIVERS
    'srl': 'srl',            # 需 napalm-srl 插件
    # Cisco 系。containerlab 的对应 kind 是 vr-ios/iosxe/iosv、nxos/nxos_ssh、vr-xr。
    # 这些 kind 此前没进映射表，厂商矩阵声称支持而代码不支持——是测试当场抓到的漂移。
    'ios': 'ios',
    'iosxe': 'ios',
    'iosv': 'ios',
    'cat9k': 'ios',
    'nxos': 'nxos',
    'nxos_ssh': 'nxos',
    'iosxr': 'iosxr',
}

# 非核心驱动：必须装对应插件才能用。装不上就如实说装不上，不静默降级。
PLUGIN_DRIVERS = {
    'nokia': 'napalm-nokia',
    'srl': 'napalm-srl',
}

# napalm 核心自带、可直接用
CORE_DRIVERS = {'eos', 'junos', 'ios', 'iosxr', 'nxos', 'nxos_ssh'}


# Linux 系但 napalm 驱不了的容器 kind。归到同一类而不是「未识别」，
# 因为它们不是未知型号——是明确知道 napalm 不支持的那一类。
LINUX_LIKE = ('linux', 'alpine', 'debian', 'ubuntu', 'centos', 'freebsd',
              'busybox', 'frr', 'frrouting', 'host', 'generic-linux')


def pick_driver(kind: str | None) -> tuple[str | None, str]:
    """返回 (driver_name, reason)。driver_name 为 None 表示这型号不该被猜。

    kind 认不出来时返回 None 而不是兜底成 eos——把未知设备当 Arista 去发命令，
    后果比报错严重得多。
    """
    k = (kind or '').strip().lower()
    if not k:
        return None, '节点未声明 kind，无法判定驱动；不猜'
    name = KIND_TO_DRIVER.get(k)
    if name:
        return name, ''
    if any(tok in k for tok in LINUX_LIKE):
        return None, (f'kind={k} 属 Linux 系容器，napalm 无此驱动。'
                      '这类设备需走 netmiko/paramiko 的直连路径，不在 napalm 采集范围内')
    return None, f'未识别的 kind={k}；不猜驱动。已知: ' + ', '.join(sorted(KIND_TO_DRIVER))


def driver_available(name: str) -> tuple[bool, str]:
    """探测驱动是否真的可导入。区分「插件没装」与「其它错误」。"""
    if name in PLUGIN_DRIVERS:
        pkg = PLUGIN_DRIVERS[name]
        try:
            __import__(pkg.replace('-', '_'))
        except ImportError:
            return False, f'需插件 {pkg}（pip install "{pkg}"）未安装'
        except Exception as exc:
            return False, f'{pkg} 导入失败: {type(exc).__name__}: {exc}'
    try:
        from napalm import get_network_driver
        get_network_driver(name)
    except ImportError as exc:
        return False, f'napalm 未安装或驱动 {name} 不可用: {exc}'
    except Exception as exc:
        return False, f'驱动 {name} 不可用: {type(exc).__name__}: {exc}'
    return True, ''
