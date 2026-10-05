from __future__ import annotations
from datetime import datetime, timezone
import os
from pathlib import Path

from .clab import parse_clab, to_graph
from .checks import run_checks
from . import reporter

def _collect_live(parsed: dict, host_map: dict[str,str], ssh_user: str, ssh_password: str,
                  ssh_port: int = 22) -> tuple[dict | None, list[str]]:
    from .drivers import driver_available, pick_driver
    from .linux_collect import collect_linux_like, is_linux_like
    collected={}
    errors=[]
    for n in parsed['nodes']:
        host=host_map.get(n['id']) or n.get('mgmt','').split('/')[0]
        if not host:
            continue
        kind=(n.get('kind') or '').lower()

        # Linux/FRR 系：napalm 驱不了，但 netmiko 可以——实验室拓扑正是这类型
        if is_linux_like(kind):
            data, why = collect_linux_like(n['id'], host, ssh_user, ssh_password, port=ssh_port)
            if data:
                collected[n['id']]=data
            else:
                errors.append(f'{n["id"]} ({host}): {why}')
            continue

        driver_name, reason = pick_driver(kind)
        if not driver_name:
            errors.append(f'{n["id"]} ({host}): {reason}')
            continue
        ok, why = driver_available(driver_name)
        if not ok:
            errors.append(f'{n["id"]} ({host}): 驱动 {driver_name} 不可用——{why}')
            continue
        try:
            from napalm import get_network_driver
            device=get_network_driver(driver_name)(hostname=host, username=ssh_user or 'admin', password=ssh_password or '', optional_args={})
            device.open()
            try:
                interfaces={name:{'is_up':bool(i['is_up']),'description':i.get('description','')} for name,i in device.get_interfaces().items()}
                collected[n['id']]={'host':host,'driver':driver_name,'interfaces':interfaces}
            finally:
                device.close()
        except Exception as exc:
            errors.append(f'{n["id"]} ({host}, {driver_name}): {type(exc).__name__}: {exc}')
    return (collected or None), errors

def diagnose(path: str, live: bool=False, host_map: dict[str,str] | None=None,
             ssh_user: str='', ssh_password: str='', llm: bool=False,
             ssh_port: int | None=None) -> dict:
    text=Path(path).read_text(encoding='utf-8')
    parsed=parse_clab(text)
    graph=to_graph(parsed)
    collected=None
    notes=[]
    if live:
        # ssh_port 必须传下去。此前 _collect_live 有 ssh_port=22 的默认参数，
        # 而 diagnose() 从不传它 —— 于是 live 采集**只能连 22 端口**，
        # 设了 NETMIND_SSH_PORT 也白设，采集必然失败。
        _port = ssh_port if ssh_port is not None else int(
            os.getenv('NETMIND_SSH_PORT', '22') or 22)
        collected, errs=_collect_live(parsed, host_map or {}, ssh_user, ssh_password,
                                      ssh_port=_port)
        if errs and not collected:
            # 每节点的失败原因必须留着。只写「都失败了」等于让人自己猜。
            notes.append(
                f'live collection failed for all nodes (port={_port}); '
                f'falling back to structure-only checks. 逐节点原因: '
                + ' | '.join(errs))
    findings=run_checks(parsed, graph, collected)
    report={
        'topology':parsed['name'],
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'mode':('live' if collected else ('live-attempted' if live else 'structure-only')),
        'node_count':len(parsed['nodes']),
        'link_count':len(parsed['links']),
        'findings':findings,
        'summary':_summarize(findings),
    }
    if notes: report['notes']=notes
    if llm:
        from .llm_enhance import enhance
        report['llm']=enhance([f for f in findings if f['severity'] in ('error','warning')],
                              context={'nodes':parsed['nodes'],'links':parsed['links']})
    return report

def _summarize(findings: list[dict]) -> str:
    counts={'error':0,'warning':0,'info':0}
    for f in findings: counts[f['severity']]+=1
    if counts['error']: return f"{counts['error']} error(s), {counts['warning']} warning(s)"
    if counts['warning']: return f"{counts['warning']} warning(s)"
    return 'clean'
