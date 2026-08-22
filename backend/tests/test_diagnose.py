import json
from pathlib import Path
from typer.testing import CliRunner
from fastapi.testclient import TestClient

from app.cli import app as cli_app, run  # noqa: F401
from app.diagnose.clab import parse_clab, to_graph
from app.diagnose.engine import diagnose

runner=CliRunner(mix_stderr=False)
DEMO=Path(__file__).resolve().parents[2]/'examples'/'clab-demo.yml'
BROKEN=Path(__file__).resolve().parents[2]/'examples'/'clab-broken.yml'

def test_parse_clab_extracts_nodes_links_addresses():
    parsed=parse_clab(DEMO.read_text(encoding='utf-8'))
    assert parsed['name']=='netmind-demo'
    ids={n['id'] for n in parsed['nodes']}
    assert {'r1','r2','sw1','client1','client2'} <= ids
    r1=next(n for n in parsed['nodes'] if n['id']=='r1')
    assert r1['mgmt']=='172.20.20.2/24'
    assert len(parsed['links'])==4 and all(len(l['endpoints'])==2 for l in parsed['links'])

def test_checks_catch_dangling_duplicate_conflict_isolation():
    report=diagnose(str(BROKEN))
    ids=[f['id'] for f in report['findings']]
    assert any(f.startswith('dangling:ghost') for f in ids)
    assert 'ip-conflict:10.0.0.1' in ids
    assert 'isolation' in ids
    assert report['mode']=='structure-only'
    assert 'error' in report['summary']

def test_clean_demo_reports_no_errors():
    report=diagnose(str(DEMO))
    errors=[f for f in report['findings'] if f['severity']=='error']
    assert errors==[]

def test_cli_diagnose_json_and_output(tmp_path):
    out=tmp_path/'report.md'
    result=runner.invoke(cli_app, ['diagnose', str(DEMO), '-o', str(out)])
    assert result.exit_code==0
    assert out.exists() and 'NetMind Diagnose Report' in out.read_text(encoding='utf-8')
    result2=runner.invoke(cli_app, ['diagnose', str(DEMO), '--json'])
    data=json.loads(result2.output)
    assert data['node_count']==5 and isinstance(data['findings'], list)

def _write(text: str) -> Path:
    import tempfile
    f=tempfile.NamedTemporaryFile('w', suffix='.yml', delete=False)
    f.write(text); f.close()
    return f.name
