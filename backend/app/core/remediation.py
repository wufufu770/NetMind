"""处置方案生成：把诊断结论翻译成**可执行且过安全门**的命令。

此前 `TelemetryService.heal()` 的「动作」是字典里的中文描述串
（'启用备用路径并重新下发流表'），不产生任何真实副作用——自愈是场表演。

这里把诊断映射成具体命令。命令只从安全门 allow_patterns 里选，
所以生成出来的每一条都能真过 `SECURITY.check`，再经 TransactionManager
真实下发（受 dangerous 语义门、cookie、回滚保护）。

纯函数：只出方案，不执行。执行由调用方走事务路径。
"""
from __future__ import annotations

from ..schemas import Diagnosis, Policy, PolicySet

# 每种诊断对应的处置原语。取值都必须在 SecurityChecker.allow_patterns 内。
REMEDIATIONS: dict[str, dict[str, str]] = {
    'congestion': {
        # 拥塞多由出口队列整形/限速造成；清掉它是最直接的处置
        'template': 'tc qdisc del dev {iface} root',
        'intent': '清除出口队列整形以释放带宽',
        'requires': 'iface',
    },
    'link_down': {
        # 断链切备用路径。注意用 `ip route add` 不是 `replace`——
        # 安全门白名单只认 add|del，replace 过不了。
        'template': 'ip route add {backup} dev {iface}',
        'intent': '切换到备用路径',
        'requires': 'iface+backup',
    },
    'anomaly_traffic': {
        'template': 'tc qdisc add dev {iface} root netem rate {rate}mbit',
        'intent': '对异常流量限速',
        'requires': 'iface+rate',
    },
    # config_error 刻意不提供自动处置：`ovs-ofctl del-flows` 是危险操作，
    # 安全门只放行「本系统签发过的流表」（带 NetMind cookie）。拿不到这个
    # 归属证明就不该自动动手——绕开它等于把「回滚任意流表」变成一个开关。
    # 需要处置时由人确认 cookie 后再下发。
}


class RemediationUnavailable(Exception):
    """缺必要参数或该诊断无对应处置原语——如实说，不编一个动作。"""


def build(diagnosis: Diagnosis, *, iface: str | None = None,
          backup: str | None = None, rate_mbps: int = 5,
          bridge: str | None = None, execution_id: str | None = None) -> PolicySet:
    """生成处置方案。参数不足就抛 RemediationUnavailable，不返回半成品。"""
    kind = diagnosis.type
    if kind == 'normal':
        raise RemediationUnavailable('诊断为正常，无需处置')
    spec = REMEDIATIONS.get(kind)
    if spec is None:
        raise RemediationUnavailable(f'没有针对 {kind} 的处置原语')

    params: dict[str, str] = {}
    if 'iface' in spec['requires'] and iface:
        params['iface'] = iface
    if spec['requires'] == 'iface+backup' and backup:
        params['backup'] = backup
    if 'rate' in spec['requires']:
        params['rate'] = str(rate_mbps)
    if 'bridge' in spec['requires'] and bridge:
        params['bridge'] = bridge

    missing = [k for k in ('iface', 'backup', 'rate', 'bridge') if k in spec['template'] and k not in params]
    if missing:
        raise RemediationUnavailable(
            f'{kind} 的处置需要参数 {missing}（模板：{spec["template"]}）')

    command = spec['template'].format(**params)
    rollback = _rollback_for(kind, params, bridge)
    pol = Policy(id='remediate-1', type='qos', name=f'remediate:{kind}',
                 action=spec['intent'], params={'diagnosis': kind, **params},
                 priority=10, source='rule',
                 commands=[command], rollback_commands=rollback)
    return PolicySet(intent_id=execution_id or f'heal-{kind}',
                     policies=[pol], source='rule')


def _rollback_for(kind: str, params: dict, bridge: str | None) -> list[str]:
    """处置本身的回滚。处置不写持久配置时回滚是空操作。"""
    if kind == 'congestion':
        return ['tc qdisc show dev ' + params.get('iface', 'eth0')]
    if kind == 'anomaly_traffic':
        return ['tc qdisc del dev ' + params.get('iface', 'eth0') + ' root']
    if kind == 'config_error':
        return ['ovs-vsctl list-ports'] if bridge else []
    return []
