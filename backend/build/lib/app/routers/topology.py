from __future__ import annotations
from fastapi import APIRouter, HTTPException
from ..core.topology import TOPOLOGY

router = APIRouter()

@router.get('/api/topology')
def topology(): return TOPOLOGY.snapshot()

@router.get('/api/topology/reachable')
def reachable(src: str, dst: str): return {'src':src,'dst':dst,'reachable':TOPOLOGY.reachable(src,dst)}

@router.get('/api/topology/nodes/{node_id}')
def topology_node(node_id: str):
    topo=TOPOLOGY.snapshot()
    node=next((n for n in topo['nodes'] if n['id']==node_id), None)
    if not node: raise HTTPException(404, 'node not found')
    links=[l for l in topo['links'] if l['source']==node_id or l['target']==node_id]
    return {'node':node,'links':links,'ports':[{'name':f'{node_id}-eth1','status':'up','rx_mbps':12.4,'tx_mbps':18.7}], 'flows':[{'priority':500,'cookie':'0x4e65744d00000001','actions':'normal'}]}
