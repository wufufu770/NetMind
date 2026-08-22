from __future__ import annotations
import yaml

SWITCH_KIND_MARKERS=('bridge','srl','ceos','vr-','crpd','ixia','keysight','ostinato')

def _node_type(kind: str) -> str:
    k=(kind or '').lower()
    if any(m in k for m in SWITCH_KIND_MARKERS):
        return 'switch'
    if k in ('linux','alpine','debian','ubuntu','centos','freebsd'):
        return 'host'
    return 'device'

def parse_clab(text: str) -> dict:
    doc=yaml.safe_load(text) or {}
    topo=doc.get('topology') or {}
    raw_nodes=topo.get('nodes') or {}
    nodes=[]
    mgmt_ips={}
    for name, cfg in raw_nodes.items():
        cfg=cfg or {}
        kind=str(cfg.get('kind') or '')
        node={'id':name,'type':_node_type(kind),'kind':kind,'image':cfg.get('image')}
        if cfg.get('mgmt_ipv4'): node['mgmt']=cfg['mgmt_ipv4']; mgmt_ips[name]=cfg['mgmt_ipv4']
        addrs=cfg.get('addresses')
        if isinstance(addrs, list):
            node['addresses']=[str(a) for a in addrs]
        elif addrs:
            node['addresses']=[str(addrs)]
        nodes.append(node)
    links=[]
    for link in topo.get('links') or []:
        endpoints=link.get('endpoints') or []
        parsed=[]
        for ep in endpoints:
            ep=str(ep)
            node, _, iface=ep.partition(':')
            parsed.append((node, iface or None))
        entry={'endpoints':parsed}
        if link.get('mtu'): entry['mtu']=int(link['mtu'])
        links.append(entry)
    return {'name':doc.get('name') or 'topology','nodes':nodes,'links':links,'mgmt_ips':mgmt_ips}

def to_graph(parsed: dict):
    from ..core.topology import TopologyGraph
    nodes=[{k:v for k,v in n.items() if k!='kind'} for n in parsed['nodes']]
    links=[]
    for l in parsed['links']:
        eps=l['endpoints']
        if len(eps)==2:
            links.append({'source':eps[0][0],'target':eps[1][0],'status':'healthy'})
    return TopologyGraph(nodes=nodes, links=links)
