from __future__ import annotations
import hashlib, json, os
from pathlib import Path

CACHE_DIR=Path(os.getenv('NETMIND_CACHE_DIR', Path.home()/'.cache'/'netmind'))

def _cache_path(model: str, payload: str) -> Path:
    digest=hashlib.sha256((model+'\x00'+payload).encode()).hexdigest()[:16]
    return CACHE_DIR/f'llm_{digest}.json'

def _client_config() -> tuple[str,str,str,str] | None:
    model=os.getenv('NETMIND_DIAGNOSE_MODEL','deepseek').strip()
    if model.startswith('ollama'):
        name=model.split(':',1)[1] if ':' in model else 'llama3.1'
        return (model,'http://localhost:11434/v1',name,'ollama')
    if model=='deepseek':
        key=os.getenv('DEEPSEEK_API_KEY','')
        if not key: return None
        return ('deepseek','https://api.deepseek.com/v1','deepseek-chat',key)
    if model=='openai':
        key=os.getenv('OPENAI_API_KEY','')
        if not key: return None
        return ('openai','https://api.openai.com/v1','gpt-4o-mini',key)
    return None

def enhance(findings: list[dict], context: dict | None=None) -> dict | None:
    if not findings:
        return None
    cfg=_client_config()
    if cfg is None:
        return {'skipped':'no LLM backend configured; set DEEPSEEK_API_KEY / OPENAI_API_KEY or NETMIND_DIAGNOSE_MODEL=ollama:<name>'}
    label, base_url, model_name, api_key=cfg
    payload=json.dumps({'findings':findings,'context':context or {}}, ensure_ascii=False)
    cache=_cache_path(label+':'+model_name, payload)
    if cache.exists():
        try:
            return {**json.loads(cache.read_text(encoding='utf-8')), 'cached': True}
        except Exception:
            pass
    prompt=(
        'You are a senior network engineer. Below is a JSON list of findings from an automated '
        'topology diagnosis. For each error/warning finding give: root-cause hypotheses ranked by '
        'likelihood, concrete verification steps, and remediation steps. Cite finding ids. '
        'Be concise and technical. Respond in markdown.\n\n'+payload
    )
    try:
        import httpx
        res=httpx.post(
            base_url.rstrip('/')+'/chat/completions',
            headers={'Authorization':f'Bearer {api_key}'},
            json={'model':model_name,'messages':[{'role':'user','content':prompt}],'temperature':0},
            timeout=30,
        )
        res.raise_for_status()
        content=res.json()['choices'][0]['message']['content']
    except Exception as exc:
        return {'skipped':f'LLM call failed: {exc}'}
    out={'model':label+':'+model_name,'analysis':content}
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass
    return out
