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
    # anomaly_traffic 刻意不提供自动处置。**它的原处置方向是反的。**
    #
    # 该诊断唯一的触发条件是「带宽相对基线跌幅 ≥50%」（diagnose() 里
    # `bw_drop >= THROUGHPUT_DROP_RATIO`），而原处置是
    # `tc qdisc add dev {iface} root netem rate {rate}mbit`——限速。
    # 也就是「带宽掉了」→「把带宽再限死一点」。
    #
    # 拿实测数据推演（tests/fixtures/lab/throughput-real.json）：
    # 健康态 21.08Mbps，限速态 4.01Mbps（跌 81% → 判 anomaly_traffic），
    # 处置要限到 5Mbps——限值高于已经跌下去的带宽，基本是空动作；
    # 链路跌到 8Mbps 时，限到 5Mbps 就是把它弄得更糟。
    #
    # 根因是这个分支原本要检测「流量过高」，但代码里**根本不存在**带宽过高的
    # 判定，只有一条「带宽跌太多」的分支，名字与触发条件对不上。
    # 带宽下降是**症状**不是病因：可能是拥塞、链路劣化、策略变更或设备故障，
    # 没有哪一条能靠限速修好。限速是对因不对症的自作主张，所以不自动做。
    #
    # config_error 同样刻意不给自动处置：`ovs-ofctl del-flows` 是危险操作，
    # 安全门只放行「本系统签发过的流表」（带 NetMind cookie）。拿不到这个
    # 归属证明就不该自动动手——绕开它等于把「回滚任意流表」变成一个开关。
}


class RemediationUnavailable(Exception):
    """缺必要参数或该诊断无对应处置原语——如实说，不编一个动作。"""


# 「我们决定不做」和「我们不知道怎么做」必须让使用者分得开。
# 缺了这份说明，运维看到「没有对应的处置原语」只能自己去翻源码，
# 才会知道这不是能力缺失而是刻意的安全选择。
NO_AUTO_REMEDIATION_REASON = {
    'anomaly_traffic': (
        'anomaly_traffic 不做自动处置：它的唯一触发条件是带宽跌幅超过一半，'
        '而原处置是限速——等于把已经掉下去的带宽再限死一点。限速修不好带宽下降，'
        '最坏还会更糟（实测健康态 21.08Mbps，限速态 4.01Mbps，限到 5Mbps 基本是空动作）。'
        '带宽下降是症状不是病因：拥塞、链路劣化、策略变更、设备故障，'
        '没有哪一条能靠限速解决。这个诊断会照常报出来，请人工判断根因。'),
    'config_error': (
        'config_error 不做自动处置：唯一可用的动作是 ovs-ofctl del-flows，'
        '属危险操作，安全门只放行本系统签发过的流表（带 NetMind cookie）。'
        '拿不到这个归属证明就动手，等于把「回滚任意流表」做成一个开关。'
        '需要时由人确认 cookie 后再下发。'),
}


# 回滚能力分级。分级的意义在于：一条只读命令不该被算作「已回滚」。
#
#   inverse —— 真逆操作。执行后设备回到处置前的状态。
#   inspect —— 只读检查。能告诉你现状，**不能撤销任何东西**。
#   none    —— 没有回滚定义。
#
# 为什么要有 inspect 这一档：清队列整形（congestion 的处置）之前若没记录原
# 参数，就**造不出**等价的逆命令。把 `tc qdisc show` 塞进 rollback_commands
# 会让「已回滚」这句话在没有回滚发生时成立——那比不提供回滚更糟。
ROLLBACK_INVERSE = 'inverse'
ROLLBACK_INSPECT = 'inspect'
ROLLBACK_NONE = 'none'

CAPABILITY_TEXT = {
    ROLLBACK_INVERSE: '可自动回滚：处置加上的变更能被等量撤销',
    ROLLBACK_INSPECT: '不可自动回滚：处置清除了原有配置但未记录其参数，无法重建',
    ROLLBACK_NONE: '无可回滚定义',
}


def _rollback_spec(kind: str, params: dict) -> tuple[str, list[str], str]:
    """返回 (能力等级, 回滚命令, 说明)。"""
    iface = params.get('iface', 'eth0')
    if kind == 'anomaly_traffic':
        # 处置是「加上限速」，逆操作就是「去掉」，等量可逆。
        return ROLLBACK_INVERSE, [f'tc qdisc del dev {iface} root'], CAPABILITY_TEXT[ROLLBACK_INVERSE]
    if kind == 'link_down':
        # 处置是「加一条路由」，逆操作就是「删掉它」。模板用 add，逆用 del，
        # 两者都在安全门白名单里（ip route add|route del）。
        backup = params.get('backup', '')
        if backup:
            return ROLLBACK_INVERSE, [f'ip route del {backup} dev {iface}'], CAPABILITY_TEXT[ROLLBACK_INVERSE]
        return ROLLBACK_NONE, [], CAPABILITY_TEXT[ROLLBACK_NONE]
    if kind == 'congestion':
        # 处置删掉了设备原有的队列整形。要恢复得知道原来是什么（netem 延迟？
        # 限速？prio 队列？），而我们处置前没采这个状态。这里如实降级为只读，
        # 并说清为什么不可回滚，而不是拿一条 show 命令冒充回滚。
        return ROLLBACK_INSPECT, [f'tc qdisc show dev {iface}'], CAPABILITY_TEXT[ROLLBACK_INSPECT]
    return ROLLBACK_NONE, [], CAPABILITY_TEXT[ROLLBACK_NONE]


def rollback_info(kind: str, params: dict | None = None) -> dict:
    """查询某种处置的回滚能力。执行方据此如实措辞，不靠猜。"""
    params = params or {}
    cap, cmds, note = _rollback_spec(kind, params)
    return {'capability': cap, 'commands': cmds, 'note': note,
            'executed': cmds if cap == ROLLBACK_INVERSE else [],
            'read_only': cmds if cap == ROLLBACK_INSPECT else []}


def build(diagnosis: Diagnosis, *, iface: str | None = None,
          backup: str | None = None,
          bridge: str | None = None, execution_id: str | None = None) -> PolicySet:
    """生成处置方案。参数不足就抛 RemediationUnavailable，不返回半成品。"""
    kind = diagnosis.type
    if kind == 'normal':
        raise RemediationUnavailable('诊断为正常，无需处置')
    spec = REMEDIATIONS.get(kind)
    if spec is None:
        raise RemediationUnavailable(
            NO_AUTO_REMEDIATION_REASON.get(kind, f'没有针对 {kind} 的处置原语'))

    params: dict[str, str] = {}
    if 'iface' in spec['requires'] and iface:
        params['iface'] = iface
    if spec['requires'] == 'iface+backup' and backup:
        params['backup'] = backup
    if 'bridge' in spec['requires'] and bridge:
        params['bridge'] = bridge

    missing = [k for k in ('iface', 'backup', 'bridge') if k in spec['template'] and k not in params]
    if missing:
        raise RemediationUnavailable(
            f'{kind} 的处置需要参数 {missing}（模板：{spec["template"]}）')

    command = spec['template'].format(**params)
    cap, rollback, _note = _rollback_spec(kind, params)
    # 只把**真逆操作**放进 rollback_commands。inspect 级命令留在 rollback_info()
    # 里，不进这个列表——一旦只读命令待在回滚列表中，执行方跑完就会报
    # rolled_back=True，在一件都没撤销的情况下说「已回滚」。
    pol = Policy(id='remediate-1', type='qos', name=f'remediate:{kind}',
                 action=spec['intent'], params={'diagnosis': kind, **params},
                 priority=10, source='rule',
                 commands=[command],
                 rollback_commands=rollback if cap == ROLLBACK_INVERSE else [])
    return PolicySet(intent_id=execution_id or f'heal-{kind}',
                     policies=[pol], source='rule')
