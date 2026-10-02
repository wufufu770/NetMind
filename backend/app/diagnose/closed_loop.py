"""真实闭环：注入 → 诊断 → 处置 → 重测 → 验证。

core/telemetry.py 的 heal() 此前是场表演：把 self.fault 改回 'normal' 再采一次
样，而 sample() 返回硬编码常量，于是「处置后恢复正常」是必然的，与是否真做了
什么无关。HealingReport.success 更直接——字段默认 True 且从无人赋值。

本模块把闭环的每一步都换成实测：

  measure(action)  真跑一次探针，拿真实测量值
  act(diagnosis)   真的动实验台（加/删 tc qdisc、断/接链路）
  verify           重测并与处置前对比，改善与否由数据说话

三条不可让步的规则：
  1. 没做重测就不许报 success——verified=False 时 success 恒为 False
  2. 重测没改善就触发回滚，而不是把「没治好」说成成功
  3. 测量失败（探针不可用）时如实记录 exception，不伪造测量值
"""
from __future__ import annotations

from typing import Callable

from ..core.telemetry import TELEMETRY
from ..schemas import Diagnosis, HealingReport, TelemetrySnapshot

# 改善判据：延迟与丢包都得降。带宽不作必需条件——延迟劣化即可构成问题，
# 与 core/telemetry.py 的诊断规则保持同一套逻辑。
LATENCY_IMPROVED_RATIO = 0.8
LOSS_IMPROVED_DELTA = 0.02


def compare(before: TelemetrySnapshot, after: TelemetrySnapshot) -> dict:
    """实测前后对比。返回改善幅度，不返回结论——结论交给调用方按判据下。"""
    b_lat, a_lat = float(before.latency_ms), float(after.latency_ms)
    b_loss, a_loss = float(before.packet_loss), float(after.packet_loss)
    lat_ratio = (a_lat / b_lat) if b_lat > 0 else None
    return {
        'latency_before_ms': b_lat,
        'latency_after_ms': a_lat,
        'latency_ratio': round(lat_ratio, 4) if lat_ratio is not None else None,
        'loss_before': b_loss,
        'loss_after': a_loss,
        'latency_improved': lat_ratio is not None and lat_ratio <= LATENCY_IMPROVED_RATIO,
        'loss_improved': (b_loss - a_loss) >= LOSS_IMPROVED_DELTA,
    }


def improved(cmp: dict) -> bool:
    return bool(cmp['latency_improved'] and cmp['loss_improved'])


def run_closed_loop(
    measure: Callable[[], dict],
    act: Callable[[Diagnosis], str],
    rollback: Callable[[], str] | None = None,
    baseline_throughput_mbps: float | None = None,
    diagnosis: Diagnosis | None = None,
) -> HealingReport:
    """跑一整轮闭环。measure/act 由调用方注入——本模块不碰 docker，
    只管顺序、判据与如实记录。I/O 边界留给适配器。"""
    from .lab_collector import to_snapshot

    before_m = measure()
    before = to_snapshot(before_m)

    d = diagnosis or TELEMETRY.diagnose([before], baseline_throughput_mbps=baseline_throughput_mbps)
    action = act(d)

    # 诊断为正常时本就不该有处置。此时「前后没变化」不是失败，而是无事可做——
    # 但也不能报 success（没有东西被治好），summary 必须把这一点说明白，
    # 否则读者会把「无需处置」误读成「处置失败」。
    no_action_needed = d.type == 'normal'

    try:
        after_m = measure()
        after = to_snapshot(after_m)
    except Exception as exc:
        # 探针挂了就是挂了，不许拿处置前的值当处置后的值
        return HealingReport(
            action_taken=action, before_snapshot=before, after_snapshot=before,
            success=False, verified=False,
            improvement={'error': f'{type(exc).__name__}: {exc}'},
            summary=f'{action}；重测失败，未验证——不报成功',
        )

    cmp = compare(before, after)
    ok = improved(cmp)

    if not ok and not no_action_needed and rollback:
        rb = rollback()
        cmp['rollback'] = rb
        try:
            after = to_snapshot(measure())
        except Exception:
            pass
        action = f'{action}；未改善→已回滚：{rb}'

    if no_action_needed:
        cmp['no_action_needed'] = True
        verdict = '诊断为正常，无需处置（不是失败，也没有东西被治好）'
    else:
        verdict = '已改善' if ok else '未改善'
    summary = (f'{action}；重测对比：延迟 {cmp["latency_before_ms"]}→{cmp["latency_after_ms"]}ms、'
               f'丢包 {cmp["loss_before"]}→{cmp["loss_after"]}（{verdict}，来源 {after.source}）')
    return HealingReport(
        action_taken=action, before_snapshot=before, after_snapshot=after,
        success=ok, verified=True, improvement=cmp, summary=summary,
    )
