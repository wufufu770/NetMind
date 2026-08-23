from __future__ import annotations
import json, os
from pathlib import Path
import typer, httpx
from rich import print
from rich.table import Table
from rich.console import Console

app=typer.Typer(help='NetMind CLI')
API=os.getenv('NETMIND_API_URL','http://localhost:8000')
console=Console()

def _headers():
    token=os.getenv('NETMIND_ADMIN_TOKEN','').strip()
    return {'Authorization':f'Bearer {token}'} if token else {}

def _get(path: str, **params):
    r=httpx.get(f'{API}{path}', params=params, timeout=20, headers=_headers())
    r.raise_for_status()
    return r.json()

def _post(path: str, data=None):
    r=httpx.post(f'{API}{path}', json=data or {}, timeout=60, headers=_headers())
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return r.text

@app.command()
def version():
    from . import __version__
    print(__version__)

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

@app.command('audit-summary')
def audit_summary():
    print(_get('/api/audit/summary'))

@app.command('tool-call')
def tool_call(tool_name: str, command: str=''):
    print(_post('/api/tools/call', {'tool_name':tool_name, 'arguments':{'command':command}}))

def run():
    app()

@app.command()
def audit(
    mode: str = typer.Option('', '--mode', help='real=连接真实设备(需 NETMIND_ENABLE_REAL_COMMANDS=true)；默认模拟演练'),
    note: str = typer.Option('', '--note', help='备注写入报告'),
):
    """只读巡检：固件版本 / SSH 口令面 / UPnP / 防火墙 / 管理端口 / 无线加密基线。"""
    payload = {'mode': mode} if mode else {}
    if note:
        payload['note'] = note
    r = _post('/api/audit/run', payload)
    tone = 'red' if r['summary']['fail'] else ('yellow' if r['summary']['warn'] else 'green')
    console.print(f"[bold]{r['audit_id']}[/] mode={r['mode']} target={r['target']} verdict=[{tone}]{r['verdict']}[/]")
    tb = Table('check', '状态', '证据')
    for c in r['checks']:
        tb.add_row(c['title'], c['status'], str(c.get('evidence', '-'))[:80])
    console.print(tb)
    console.print(f"报告: {r.get('report_path','-')}")

@app.command('diagnose')
def diagnose_cmd(
    topology: str = typer.Argument(..., help='containerlab topology YAML path'),
    json_output: bool = typer.Option(False, '--json', help='machine-readable output'),
    output: str = typer.Option(None, '--output', '-o', help='write report to file instead of stdout'),
    live: bool = typer.Option(False, '--live', help='collect interface state via napalm (requires netmind[drivers])'),
    host: list[str] = typer.Option([], '--host', help='node-to-address mapping, repeatable: --host r1=10.0.0.5'),
    llm: bool = typer.Option(False, '--llm', help='enrich findings with LLM root-cause analysis (needs DEEPSEEK_API_KEY or NETMIND_DIAGNOSE_MODEL)'),
):
    """Diagnose a containerlab topology: structure checks first, optional live collection, optional LLM analysis."""
    from .diagnose.engine import diagnose as _run
    from .diagnose import reporter
    hm={}
    for h in host:
        name, _, ip=h.partition('=')
        if name.strip() and ip.strip(): hm[name.strip()]=ip.strip()
    report=_run(topology, live=live, host_map=hm,
                ssh_user=os.getenv('NETMIND_SSH_USERNAME',''), ssh_password=os.getenv('NETMIND_SSH_PASSWORD',''), llm=llm)
    text=reporter.render_json(report) if json_output else reporter.render_md(report)
    if output:
        Path(output).write_text(text, encoding='utf-8')
        print(f'wrote {output}')
    else:
        import sys
        sys.stdout.write(text + '\n')

if __name__ == '__main__':
    run()
