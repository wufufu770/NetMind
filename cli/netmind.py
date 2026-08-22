from __future__ import annotations
import json
import typer, httpx
from rich import print
from rich.table import Table
from rich.console import Console

app=typer.Typer(help='NetMind CLI')
API='http://localhost:8000'
console=Console()

def _get(path: str, **params):
    r=httpx.get(f'{API}{path}', params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def _post(path: str, data=None):
    r=httpx.post(f'{API}{path}', json=data or {}, timeout=60)
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return r.text

@app.command()
def status():
    print(_get('/api/system/status'))

@app.command()
def submit(text: str, dry_run: bool=False):
    print(_post('/api/intent/submit', {'text':text,'dry_run':dry_run}))

@app.command()
def history():
    rows=_get('/api/executions')
    t=Table('execution_id','business','status','created_at')
    for e in rows:
        t.add_row(e['execution_id'], (e.get('intent') or {}).get('business','-'), e['status'], e['created_at'])
    console.print(t)

@app.command()
def replay(execution_id: str):
    print(_get(f'/api/executions/{execution_id}/replay'))

@app.command()
def logs(limit: int=30, q: str=''):
    path='/api/logs/search' if q else '/api/logs'
    rows=_get(path, limit=limit, q=q) if q else _get(path, limit=limit)
    for row in rows:
        print(f"{row['ts']} [{row['level']}] {row['source']}: {row['message']}")

@app.command()
def report(execution_id: str):
    r=httpx.get(f'{API}/api/report/{execution_id}.md', timeout=20)
    r.raise_for_status()
    print(r.text)

@app.command()
def fault(kind: str='congestion'):
    print(_post('/api/experiment/fault', {'kind':kind}))

@app.command()
def heal():
    print(_post('/api/telemetry/heal'))

@app.command('config-export')
def config_export(path: str='netmind_config.json'):
    data=_get('/api/config/export')
    open(path,'w',encoding='utf-8').write(json.dumps(data,ensure_ascii=False,indent=2))
    print(f'wrote {path}')

@app.command('config-export-yaml')
def config_export_yaml(path: str='netmind_config.yml'):
    r=httpx.get(f'{API}/api/config/export.yaml', timeout=20)
    r.raise_for_status()
    open(path,'w',encoding='utf-8').write(r.text)
    print(f'wrote {path}')

@app.command()
def scenario(name: str='defense'):
    print(_post(f'/api/experiment/scenario/{name}', {}))

@app.command()
def audit():
    print(_get('/api/audit/summary'))

@app.command('tool-call')
def tool_call(tool_name: str, command: str=''):
    print(_post('/api/tools/call', {'tool_name':tool_name, 'arguments':{'command':command}}))

if __name__ == '__main__':
    app()
