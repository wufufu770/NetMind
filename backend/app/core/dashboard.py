"""面板数据推导：纯函数，输入是 store 的真实状态，输出是面板要的形状。

此前这些数字是写死在路由里的常量（`sla: 98`、`active_intents: 2`、三条固定的
风险文案），而诚实表里并没有对应条目声明它们是模拟的。对一个以「不编数据」为
纪律的项目来说，这是最该先拆掉的一处：读者无从判断 98 是测出来的还是编的。

现在全部由真实状态推出；**算不出来的字段返回 None 并带上原因**，不用看起来
合理的数字占位。SLA 达成率就是典型——它需要一个事先约定的 SLO 目标值，
项目里没有，就不该有 SLA 这个数。
"""
from __future__ import annotations

from typing import Any, Iterable

# 处于这两种状态的执行算「进行中」
ACTIVE_STATUSES = ('running', 'warning')
# 风险条目里引用的最近窗口
RISK_WINDOW = 20
# 丢包达到这个比例才算一条风险（与 core/telemetry.py 的判据同源）
LOSS_RISK = 0.05


def build_dashboard(*, executions: Iterable[Any], telemetry: Iterable[Any],
                    logs: Iterable[Any], topology: dict | None = None) -> dict:
    """推导面板。所有数字都必须能在传入的状态里找到出处。"""
    ex = list(executions)
    tel = list(telemetry)
    recent = tel[-RISK_WINDOW:]

    active = [e for e in ex if _status(e) in ACTIVE_STATUSES]
    latest = tel[-1] if tel else None

    return {
        'metrics': {
            'latency_ms': _num(getattr(latest, 'latency_ms', None)),
            'packet_loss': _num(getattr(latest, 'packet_loss', None)),
            'active_intents': len(active),
            # 没有事先约定的 SLO 就没有达成率。这里不拿「延迟够低」反推一个
            # SLA 数字——那等于凭空造一个最重要的指标。
            'sla': None,
            'sla_reason': '未定义 SLO 目标值；达成率需要与约定的目标比对，'
                          '项目内不存在该目标，故不提供此指标',
        },
        'risks': _risks(recent, active),
        'active_intents': [
            {'execution_id': getattr(e, 'execution_id', '?'),
             'title': getattr(e, 'intent_text', '') or '(无意图文本)',
             'status': _status(e)}
            for e in active
        ],
        'events': [_log(l) for l in list(logs)[-8:]],
        'topology': topology or {'nodes': [], 'links': []},
        'provenance': {
            'execution_count': len(ex),
            'telemetry_samples': len(tel),
            'telemetry_source': str(getattr(latest, 'source', '')) if latest else '',
            'sla_computed': False,
        },
    }


def _status(e: Any) -> str:
    s = getattr(e, 'status', '')
    return getattr(s, 'value', s) or ''


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _risks(recent: list, active: list) -> list[dict]:
    """风险只从真实观测里推。没有观测就没有风险条目，不放占位文案。"""
    out = []
    alerts = [t for t in recent if getattr(t, 'alert', False)]
    if alerts:
        worst = max(alerts, key=lambda t: _num(getattr(t, 'latency_ms', 0)) or 0.0)
        out.append({
            'title': f'遥测告警 {len(alerts)}/{len(recent)} 次，最高达 '
                     f'{_num(getattr(worst, "latency_ms", None))}ms',
            'severity': 'warning',
            'evidence': {'alert_samples': len(alerts), 'window': len(recent),
                         'source': str(getattr(worst, 'source', ''))},
        })
    lossy = [t for t in recent
             if (_num(getattr(t, 'packet_loss', None)) or 0.0) >= LOSS_RISK]
    if lossy:
        out.append({
            'title': f'丢包率超过 {LOSS_RISK:.0%} 的采样 {len(lossy)} 个',
            'severity': 'warning',
            'evidence': {'samples': len(lossy), 'threshold': LOSS_RISK},
        })
    if active:
        out.append({
            'title': f'{len(active)} 个意图仍在执行中',
            'severity': 'info',
            'evidence': {'execution_ids': [getattr(e, 'execution_id', '?') for e in active][:5]},
        })
    return out


def _log(l: Any) -> dict:
    return {'source': getattr(l, 'source', ''), 'level': getattr(l, 'level', ''),
            'message': getattr(l, 'message', ''), 'ts': str(getattr(l, 'ts', ''))}
