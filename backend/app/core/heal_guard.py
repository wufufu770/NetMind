"""自动处置的目标与次数护栏。

自愈要往真设备上下命令，就必须先回答两个问题：**动哪块**、**动几次**。
这两个问题都答不出来时，正确做法是**不动**，并把「为什么没动」说清楚。

## 为什么要显式配接口

处置命令长成 `tc qdisc del dev {iface} root`。iface 猜错，命令就会下到
错误的口上——在一个有多个接口的真实设备上，那可能正好是管理口。
项目对设备采集的立场一直是「不知道就如实拒绝，不猜驱动」，处置更不该猜：
采集错了只是读不到，处置错了是改坏别人的网络。

于是 `NETMIND_HEAL_IFACE` 不配就不自动处置。此时调用方拿到的是
`disabled` 说明，而不是一条编出来的命令。

## 为什么要有次数上限

同一个故障反复处置，除了刷日志没别的意义，还可能把设备反复推来推去。
这里按 (诊断类型, 接口) 记账：连续失败达到上限就停，转人工。计数落在
STORE 里，重启不清零——否则「重启一下就又能试一轮」等于没有上限。
"""
from __future__ import annotations

import os
import time

IFACE_ENV = 'NETMIND_HEAL_IFACE'
BACKUP_ENV = 'NETMIND_HEAL_BACKUP_ROUTE'
MAX_ATTEMPTS_ENV = 'NETMIND_HEAL_MAX_ATTEMPTS'
# 业界常见区间 5–10；这里默认取 3，因为处置的是真实网络，
# 一次故障连下三次同样的命令还没见效，就该让人来看了。
DEFAULT_MAX_ATTEMPTS = 3
# 两次尝试之间至少隔这么久，防抖；可由环境变量调。
COOLDOWN_SEC = 60.0


class HealingDisabled(Exception):
    """没配处置目标——自动处置处于关闭状态，不是「失败了」。"""


class AttemptCapReached(Exception):
    """同一故障的连续处置次数已达上限，转人工。"""


def heal_iface() -> str | None:
    v = os.getenv(IFACE_ENV, '').strip()
    return v or None


def heal_backup_route() -> str | None:
    v = os.getenv(BACKUP_ENV, '').strip()
    return v or None


def max_attempts() -> int:
    try:
        n = int(os.getenv(MAX_ATTEMPTS_ENV, '').strip() or DEFAULT_MAX_ATTEMPTS)
    except ValueError:
        n = DEFAULT_MAX_ATTEMPTS
    return max(1, n)


def target_for(diagnosis_type: str) -> dict:
    """该诊断的处置目标。缺必要项就抛 HealingDisabled，并说明缺什么。"""
    iface = heal_iface()
    if not iface:
        raise HealingDisabled(
            f'未配置 {IFACE_ENV}，自动处置未启用。处置命令必须指定接口'
            f'（如 tc qdisc del dev <iface> root），而项目不猜接口——'
            f'猜错会把命令下到错误的口上。配好该变量后自愈才会真正动作。')
    out: dict = {'iface': iface}
    if diagnosis_type == 'link_down':
        backup = heal_backup_route()
        if not backup:
            raise HealingDisabled(
                f'link_down 的处置需要备用路径，但未配置 {BACKUP_ENV}。'
                f'示例值：NETMIND_HEAL_BACKUP_ROUTE="10.9.0.0/24 via 192.0.2.9"')
        out['backup'] = backup
    return out


# ------------------------------------------------------------------ 次数记账

def _key(kind: str, iface: str) -> str:
    return f'{kind}@{iface}'


def check_attempt(store, kind: str, iface: str, now: float | None = None) -> int:
    """检查是否还能再处置一次。返回当前已连续失败次数。

    成功过一次就清零——故障确实被修好过，下一次是新问题，不该继承旧账。
    """
    t = time.time() if now is None else now
    rec = store.heal_attempts.get(_key(kind, iface))
    if not rec:
        return 0
    if t - float(rec.get('last', 0)) > COOLDOWN_SEC:
        # 冷却期已过，旧账作废——否则一次偶发失败会永久锁住后续处置
        store.heal_attempts.pop(_key(kind, iface), None)
        return 0
    return int(rec.get('count', 0))


def record_failure(store, kind: str, iface: str, now: float | None = None) -> int:
    t = time.time() if now is None else now
    k = _key(kind, iface)
    n = check_attempt(store, kind, iface, t) + 1
    store.heal_attempts[k] = {'count': n, 'last': t, 'execution': store.last_heal_execution}
    store.mark_dirty()
    return n


def record_success(store, kind: str, iface: str) -> None:
    store.heal_attempts.pop(_key(kind, iface), None)
    store.mark_dirty()


def guard(store, kind: str, iface: str, now: float | None = None) -> int:
    """次数护栏。超限抛 AttemptCapReached，带上已试次数与上限。"""
    n = check_attempt(store, kind, iface, now)
    cap = max_attempts()
    if n >= cap:
        raise AttemptCapReached(
            f'{kind}@{iface} 已连续处置 {n} 次未奏效（上限 {cap}，'
            f'冷却 {COOLDOWN_SEC:.0f}s），停止自动处置并转人工介入。'
            f'确认根因后调大 {MAX_ATTEMPTS_ENV} 或清理计数可恢复。')
    return n
