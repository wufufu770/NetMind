"""Linux 系设备的只读采集走 netmiko 直连，不走 napalm。

为什么单独一条：napalm 5.2 核心只带 eos/junos/ios/iosxr/nxos/nxos_ssh，
驱动不了 Linux/FRR 系容器。而实验室拓扑（examples/clab-demo.yml）恰恰是
FRR + alpine。实测 netmiko 的 device_type='linux' 对这类设备可用：

    ConnectHandler(device_type='linux', host=..., port=2222,
                   username=..., password=...) → send_command() 正常返回

所以「不支持」这句话是错的——不是做不到，是原来的实现只挂了 napalm 一条路。
这里补上第二条，并把 netmiko 的失败原样报出去，不吞。
"""
from __future__ import annotations

from ..diagnose.drivers import LINUX_LIKE

# 只读命令白名单。这个路径不接「下发」，只采状态。
# 命令按 BusyBox 兼容性选：实验台的 alpine / FRR 容器里 ip 没有 -br（brief）选项，
# 用了会把用法说明当输出收回来——那种「看起来有数据其实是报错」的污染最难发现。
READONLY_COMMANDS = {
    'interfaces': 'ip addr show',
    'routes': 'ip route show',
    'uptime': 'cat /proc/uptime',
}

# 命令实际没跑成时，shell 会打这些。用它们识别「假数据」，宁可标失败也不收垃圾。
_ERROR_MARKERS = ('usage:', 'not found', 'no such', 'invalid option',
                   'syntax error', 'sh: ', 'not a directory')


def _looks_like_error(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _ERROR_MARKERS) or low.strip().startswith('usage')


def is_linux_like(kind: str | None) -> bool:
    k = (kind or '').strip().lower()
    return any(tok in k for tok in LINUX_LIKE)


def collect_linux_like(node_id: str, host: str, username: str, password: str,
                       port: int = 2222, timeout: int = 15) -> tuple[dict | None, str]:
    """真连一次，采三样只读状态。失败返回 (None, 原因)，不伪造。"""
    try:
        import netmiko
    except ImportError:
        return None, 'netmiko 未安装（pip install "netmind[drivers]"）'
    try:
        conn = netmiko.ConnectHandler(
            device_type='linux', host=host, port=port,
            username=username or '', password=password or '', timeout=timeout)
    except Exception as exc:
        return None, f'SSH 失败 {type(exc).__name__}: {str(exc)[:160]}'
    try:
        out = {}
        failed = []
        for key, cmd in READONLY_COMMANDS.items():
            try:
                # 不用 strip=True——那是 napalm ConnectionHelper 的签名，netmiko 的
                # BaseConnection.send_command 不收这个参数（实测 TypeError）。手动 strip。
                text = str(conn.send_command(cmd)).strip()
            except Exception as exc:
                out[key] = None
                failed.append(f'{key}: {type(exc).__name__}: {str(exc)[:60]}')
                continue
            if not text:
                out[key] = None
                failed.append(f'{key}: 空输出')
            elif _looks_like_error(text):
                # 命令没跑成，收到的是用法/报错文本。收下来就是假数据——标失败。
                out[key] = None
                failed.append(f'{key}: 返回的是报错/用法文本，未采到数据')
            else:
                out[key] = text
        data = {'host': host, 'port': port, 'transport': 'netmiko/linux', 'collected': out}
        if failed:
            data['partial'] = failed
        return data, ''
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass
