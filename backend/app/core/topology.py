from collections import defaultdict, deque

class TopologyGraph:
    def __init__(self):
        self.nodes=[
            {'id':'teacher_terminal','type':'host','status':'healthy'},
            {'id':'student_terminal','type':'host','status':'healthy'},
            {'id':'guest_terminal','type':'host','status':'limited'},
            {'id':'s1','type':'switch','status':'healthy'},
            {'id':'meeting_server','type':'server','status':'healthy'},
            {'id':'lab_server','type':'server','status':'healthy'},
            {'id':'s2','type':'switch','status':'standby'}
        ]
        self.links=[
            {'source':'teacher_terminal','target':'s1','latency_ms':8,'status':'healthy'},
            {'source':'student_terminal','target':'s1','latency_ms':12,'status':'healthy'},
            {'source':'guest_terminal','target':'s1','latency_ms':18,'status':'limited'},
            {'source':'s1','target':'meeting_server','latency_ms':15,'status':'healthy'},
            {'source':'s1','target':'lab_server','latency_ms':17,'status':'healthy'},
            {'source':'s1','target':'s2','latency_ms':28,'status':'standby'},
            {'source':'s2','target':'meeting_server','latency_ms':20,'status':'standby'},
        ]
    def snapshot(self): return {'nodes':self.nodes,'links':self.links}
    def reachable(self, src, dst):
        g=defaultdict(list)
        for l in self.links:
            if l.get('status') != 'down':
                g[l['source']].append(l['target']); g[l['target']].append(l['source'])
        q=deque([src]); seen={src}
        while q:
            n=q.popleft()
            if n==dst: return True
            for m in g[n]:
                if m not in seen: seen.add(m); q.append(m)
        return False

TOPOLOGY=TopologyGraph()
