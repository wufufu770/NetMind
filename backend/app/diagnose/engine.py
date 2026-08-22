from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

from .clab import parse_clab, to_graph
from .checks import run_checks
from . import reporter

def _collect_live(parsed: dict, host_map: dict[str,str], ssh_user: str, ssh_password: str) -> tuple[dict | None, list[str]]:
    try:
        from napalm import get_network_driver
    except ImportError:
        return None, ['napalm not installed (pip install "netmind[drivers]"); live collection unavailable']
    collected={}
    errors=[]
    for n in parsed['nodes']:
        host=host_map.get(n['id']) or n.get('mgmt','').split('/')[0]
        if not host:
            continue
        kind=(n.get('kind') or 'linux').lower()
        driver_name={'vr-sros':'nokia','vr-vmx':'junos','ceos':'eos','srl':'srl','crpd':'junos'}.get(kind,'linux' if 'linux' in kind else 'eos')
        try:
            device=get_network_driver(driver_name)(hostname=host, username=ssh_user or 'admin', password=ssh_password or '', optional_args={})
            device.open()
            try:
                interfaces={name:{'is_up':bool(i['is_up']),'description':i.get('description','')} for name,i in device.get_interfaces().items()}
                collected[n['id']]={'host':host,'interfaces':interfaces}
            finally:
                device.close()
        except Exception as exc:
            errors.append(f'{n["id"]} ({host}): {exc}')
    return (collected or None), errors

def diagnose(path: str, live: bool=False, host_map: dict[str,str] | None=None,
             ssh_user: str='', ssh_password: str='', llm: bool=False) -> dict:
    text=Path(path).read_text(encoding='utf-8')
    parsed=parse_clab(text)
    graph=to_graph(parsed)
    collected=None
    notes=[]
    if live:
        collected, errs=_collect_live(parsed, host_map or {}, ssh_user, ssh_password)
        if errs and not collected:
            notes.append('live collection failed for all nodes; falling back to structure-only checks')
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
