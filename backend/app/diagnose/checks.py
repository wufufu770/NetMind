from __future__ import annotations

def run_checks(parsed: dict, graph, collected: dict | None=None) -> list[dict]:
    findings=[]
    node_ids={n['id'] for n in parsed['nodes']}

    for l in parsed['links']:
        for node, iface in l['endpoints']:
            if node not in node_ids:
                findings.append({'id':f'dangling:{node}','severity':'error',
                                 'title':f'Link endpoint references unknown node "{node}"',
                                 'detail':f'Endpoint {node}:{iface or "?"} has no matching topology node.'})
            elif not iface:
                findings.append({'id':f'iface-missing:{node}','severity':'warning',
                                 'title':f'Endpoint on "{node}" lacks an interface name',
                                 'detail':'Links without interface names cannot be validated against live state.'})

    seen={}
    for i,l in enumerate(parsed['links']):
        pair=tuple(sorted(e[0] for e in l['endpoints']))
        if len(pair)==2 and pair==tuple(sorted(set(pair))):
            key=(pair,i)
        else:
            continue
        if pair in seen:
            findings.append({'id':f'dup-link:{pair[0]}-{pair[1]}','severity':'warning',
                             'title':f'Duplicate link between {pair[0]} and {pair[1]} (links {seen[pair]} and {i})',
                             'detail':'Parallel links may be intentional (LAG) but are unlabelled.'})
        else:
            seen[pair]=i
        if len(set(l['endpoints']))<2:
            findings.append({'id':f'self-loop:{l["endpoints"][0][0]}:{i}','severity':'warning',
                             'title':'Self-loop link','detail':f'Link {i} connects {l["endpoints"]} to itself.'})

    ips={}
    for n in parsed['nodes']:
        for ip in ([n.get('mgmt')] + list(n.get('addresses') or [])):
            if ip:
                if ip in ips:
                    findings.append({'id':f'ip-conflict:{ip}','severity':'error',
                                     'title':f'Address conflict: {ip} assigned to both {ips[ip]} and {n["id"]}',
                                     'detail':'Duplicate addressing causes unreachable hosts and ARP churn.'})
                else:
                    ips[ip]=n['id']

    components=_components(graph)
    if len(components)>1:
        parts=[', '.join(sorted(c)) for c in components]
        findings.append({'id':'isolation','severity':'warning',
                         'title':f'Topology splits into {len(components)} isolated groups',
                         'detail':'Groups: '+' | '.join(parts)+'.'})

    for n in parsed['nodes']:
        if n.get('mgmt'):
            import ipaddress
            try:
                ipaddress.ip_address(n['mgmt'].split('/')[0])
            except ValueError:
                findings.append({'id':f'mgmt-invalid:{n["id"]}','severity':'error',
                                 'title':f'Management address of {n["id"]} is invalid: {n.get("mgmt")}',
                                 'detail':'Not a parseable IPv4/IPv6 address.'})

    if collected:
        for node_id, data in collected.items():
            down=[name for name, iface in (data.get('interfaces') or {}).items() if not iface.get('is_up', True)]
            for name in down:
                findings.append({'id':f'iface-down:{node_id}:{name}','severity':'warning',
                                 'title':f'Interface {name} is down on {node_id}',
                                 'detail':data['interfaces'][name].get('description') or ''})
    else:
        findings.append({'id':'collection-skipped','severity':'info',
                         'title':'Live collection skipped (no device access requested)',
                         'detail':'Interface-level checks require --live with reachable nodes; this report validates topology structure only.'})

    severity_rank={'error':0,'warning':1,'info':2}
    findings.sort(key=lambda f:(severity_rank[f['severity']], f['id']))
    return findings

def _components(graph) -> list[list[str]]:
    adj={n['id']: set() for n in graph.nodes}
    for l in graph.links:
        s,t=l['source'],l['target']
        if s in adj and t in adj:
            adj[s].add(t); adj[t].add(s)
    seen=set(); out=[]
    for node in adj:
        if node in seen: continue
        stack=[node]; comp=[]
        while stack:
            cur=stack.pop()
            if cur in seen: continue
            seen.add(cur); comp.append(cur)
            stack.extend(adj[cur]-seen)
        out.append(sorted(comp))
    return sorted(out, key=len)
