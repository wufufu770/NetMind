"""配置变更提案（config-diff）。

在下发之前把「将改什么」显式摊开——Phase 2 的第一块。当前实现只做 diff 与
危险标注，不做校验也不做下发：校验属于 verification，下发属于 deploy。

纯函数，无 I/O。渲染出的 Markdown 是给人评审的产物，下游可交给 ArgoCD 之类的
GitOps 流程，但本模块不假设有 GitOps 环境存在。
"""
from __future__ import annotations

from typing import Callable, Iterable

from ..schemas import Policy, PolicySet

RISK_ORDER = {'low': 0, 'medium': 1, 'high': 2}


def _key(p: Policy) -> str:
    return p.id


def _fingerprint(p: Policy) -> dict:
    return {
        'type': p.type, 'name': p.name, 'action': p.action,
        'params': p.params, 'priority': p.priority,
        'commands': list(p.commands), 'rollback_commands': list(p.rollback_commands),
    }


def _field_changes(before: Policy, after: Policy) -> dict:
    fb, fa = _fingerprint(before), _fingerprint(after)
    return {k: {'from': fb[k], 'to': fa[k]} for k in fb if fb[k] != fa[k]}


def diff_policies(
    current: Iterable[Policy],
    proposed: Iterable[Policy],
    is_dangerous: Callable[[str], bool] | None = None,
) -> dict:
    """产出结构化 diff。is_dangerous 缺省时全部按 low 处理，不臆测风险。"""
    cur = {_key(p): p for p in current}
    pro = {_key(p): p for p in proposed}

    added, removed, changed, unchanged = [], [], [], []
    for k in sorted(set(pro) - set(cur)):
        added.append(pro[k])
    for k in sorted(set(cur) - set(pro)):
        removed.append(cur[k])
    for k in sorted(set(cur) & set(pro)):
        fields = _field_changes(cur[k], pro[k])
        if fields:
            changed.append({'policy': pro[k], 'fields': fields})
        else:
            unchanged.append(pro[k])

    def risk(p: Policy) -> str:
        if is_dangerous is None:
            return 'low'
        return 'high' if any(is_dangerous(c) for c in p.commands) else 'low'

    items = ([{'op': 'add', 'policy': p, 'risk': risk(p)} for p in added]
             + [{'op': 'remove', 'policy': p, 'risk': 'low'} for p in removed]
             + [{'op': 'modify', 'policy': c['policy'], 'fields': c['fields'], 'risk': risk(c['policy'])}
                for c in changed])
    items.sort(key=lambda x: (-RISK_ORDER.get(x['risk'], 0), x['policy'].id))

    return {
        'added': added, 'removed': removed, 'changed': changed, 'unchanged': unchanged,
        'items': items,
        'summary': {
            'added': len(added), 'removed': len(removed),
            'modified': len(changed), 'unchanged': len(unchanged),
            'requires_approval': any(i['risk'] == 'high' for i in items),
        },
    }


def diff_policy_set(current: Iterable[Policy], proposed: PolicySet,
                    is_dangerous: Callable[[str], bool] | None = None) -> dict:
    return diff_policies(current, proposed.policies, is_dangerous)


def render_markdown(d: dict) -> str:
    """把 diff 渲染成可评审的 Markdown。不加营销词——这是给人签字看的单据。"""
    s = d['summary']
    out = [f'# 变更提案 {s["added"]} 增 / {s["modified"]} 改 / {s["removed"]} 删 / {s["unchanged"]} 不变', '']
    if s['requires_approval']:
        out += ['> 含危险操作，必须走审批流。', '']
    if not d['items']:
        out += ['无变更。', '']
        return '\n'.join(out)
    for it in d['items']:
        p: Policy = it['policy']
        tag = '⚠️' if it['risk'] == 'high' else ''
        out.append(f'## {it["op"]} `{p.id}` {p.type}/{p.name} {tag}'.rstrip())
        if it['op'] == 'modify':
            for f, ch in it['fields'].items():
                out.append(f'- `{f}`: {ch["from"]!r} → {ch["to"]!r}')
        else:
            out.append(f'- `action`: {p.action!r}')
            if p.params:
                out.append(f'- `params`: {p.params!r}')
        if p.commands:
            out.append(f'- `commands`:')
            out += [f'  - `{c}`' for c in p.commands]
        if p.rollback_commands:
            out.append(f'- `rollback_commands`:')
            out += [f'  - `{c}`' for c in p.rollback_commands]
        out.append('')
    return '\n'.join(out)
