from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_langgraph_compat_interrupt_resume():
    graph = client.get('/api/langgraph/graph').json()
    assert graph['engine'] in ('LangGraphCompatEngine', 'langgraph.StateGraph')
    assert any(e['condition'] != 'always' for e in graph['edges'])
    run = client.post('/api/langgraph/run?require_approval=true', json={'intent_text':'保障答辩视频会议延迟低于50ms','dry_run':False}).json()
    assert run['interrupts']
    iid = run['interrupts'][0]['interrupt_id']
    resumed = client.post(f'/api/langgraph/resume/{iid}', json={'decision':'approved'}).json()
    assert resumed['ok'] is True


def test_mcp_protocol_and_tool_call():
    listing = client.get('/api/mcp/list_tools').json()
    assert listing['protocol'] == 'mcp-compatible-local'
    assert listing['tools']
    called = client.post('/api/mcp/call_tool', json={'tool_name':'topology_tool','arguments':{},'dry_run':True}).json()
    assert called['result']['ok'] is True
    server = client.post('/api/mcp/servers/local-test/test', json={'transport':'http','url':'http://localhost/mock'}).json()
    assert server['ok'] is True


def test_chat_tool_sequence_and_repository_status():
    ex = client.post('/api/intent/submit', json={'text':'今晚保障答辩视频会议，访客限速5Mbps'}).json()
    chat = client.post('/api/chat/ask', json={'question':'当前网络状态怎么样？','model_id':'mock'}).json()
    assert chat['read_only'] is True
    seq = client.get(f"/api/executions/{ex['execution_id']}/tool-sequence").json()
    assert seq['items']
    repo = client.get('/api/repository/status').json()
    assert 'active_store' in repo
    probe = client.post('/api/repository/sqlite-probe').json()
    assert probe['ok'] is True


def test_config_security_fonts_credentials_and_rich_report():
    sec = client.get('/api/config/security').json()
    assert 'allowlist' in sec
    sec2 = client.put('/api/config/security', json={'unattended_policy':'deny'}).json()
    assert sec2['unattended_policy'] == 'deny'
    fonts = client.put('/api/config/fonts', json={'custom_font_url':'https://example.com/font.woff2'}).json()
    assert fonts['custom_font_url'].endswith('.woff2')
    cred = client.post('/api/config/credentials', json={'name':'lab-ovs','driver':'ssh','host':'10.0.0.2','username':'netmind','secret_ref':'vault://lab-ovs'}).json()
    assert cred['host'] == '10.0.0.2'
    ex = client.post('/api/intent/submit', json={'text':'访客网络限速5Mbps'}).json()
    html = client.get(f"/api/report/{ex['execution_id']}/rich.html")
    assert html.status_code == 200 and 'text/html' in html.headers['content-type']
    pdf = client.get(f"/api/report/{ex['execution_id']}/rich.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')


def test_v4_completion_report_non_environment_is_100():
    report = client.get('/api/v4/completion-report').json()
    assert report['non_environment_completion_percent'] == 100
    assert report['non_environment_incomplete'] == []
