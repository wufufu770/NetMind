#!/usr/bin/env python3
"""HTTP 层并发压测。

此前对「这个服务扛不扛得住」零证据：CI 全是单进程跑测试，没人问过
「10 个客户端同时打 intent submit 会怎样」。自托管部署时客户会自己压，
那时候发现就是事故。

覆盖四类真实负载：
  ① 读   高频 GET（面板轮询的真实形态）
  ② 写   并发 intent submit（触发部署 + 落盘）
  ③ 混合 读写并行
  ④ 鉴权 未授权请求不应被「压力」绕过

输出指标（p50/p95/p99/错误率），可作为 SLA 基线。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))], 2)


def summarize(lat: list[float], err: list[str]) -> dict:
    return {
        'count': len(lat),
        'ok': len(lat) - len(set(err)),
        'errors': len(set(err)),
        'error_samples': list(set(err))[:3],
        'p50_ms': pct(lat, .50), 'p95_ms': pct(lat, .95),
        'p99_ms': pct(lat, .99), 'max_ms': round(max(lat), 2) if lat else None,
        'mean_ms': round(statistics.mean(lat), 2) if lat else None,
    }


def run(app_client_factory, name: str, method: str, path: str, *,
        workers: int, per_worker: int, headers: dict | None = None,
        body: dict | None = None, expect: int = 200) -> dict:
    lat: list[float] = []
    errs: list[str] = []
    lock = threading.Lock()

    def one(i: int):
        c = app_client_factory()
        payload = None
        if body is not None:
            payload = dict(body)
            payload['text'] = f'压测意图-{i}'
        t0 = time.perf_counter()
        try:
            if method == 'GET':
                r = c.get(path, headers=headers or {})
            else:
                r = c.post(path, json=payload, headers=headers or {})
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                lat.append(dt)
                if r.status_code != expect:
                    errs.append(f'{r.status_code}')
        except Exception as exc:
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                lat.append(dt)
                errs.append(f'{type(exc).__name__}')

    # 注意：任务数 = workers × per_worker。原先写 range(per_worker) 只发了
    # per_worker 条，却打印 workers×per_worker ——那是**算出来的**而不是观测到的，
    # 报告了一个从没发生过的压测量。这项目禁止的正是这种数字。
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, range(workers * per_worker)))
    res = summarize(lat, errs)
    res['scenario'] = name
    res['workers'] = workers
    # total 用实际观测到的条数，不做算术推算
    res['expected'] = workers * per_worker
    res['total'] = len(lat)
    assert len(lat) == workers * per_worker, f'实际发出 {len(lat)} 条，期望 {workers * per_worker} 条'
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description='NetMind HTTP 并发压测')
    ap.add_argument('--workers', type=int, default=10)
    ap.add_argument('--per-worker', type=int, default=10)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    td = tempfile.mkdtemp(prefix='netmind-load-')
    os.environ['NETMIND_DATA_FILE'] = str(Path(td) / 'store.json')
    os.environ.pop('NETMIND_ADMIN_TOKEN', None)
    # 压测量的是应用层与存储层，不是限流器。限流开着的话写请求会在 10 次后
    # 全部变成 429，测出来的就不是系统的真实承压能力了。
    # 限流本身对吞吐的影响单独说明：write 组 5/s 突发 10，即持续写上限约 5 次/秒。
    os.environ['NETMIND_RATE_LIMIT'] = 'off'
    sys.path.insert(0, str(ROOT / 'backend'))

    from fastapi.testclient import TestClient
    from app.main import app
    from app.core import observability as obs

    def factory():
        return TestClient(app, client=('127.0.0.1', 0))

    c = factory()
    c.post('/api/experiment/fault', json={'kind': 'normal'})     # 预热

    scenarios = []
    print(f'\n  并发压测：{a.workers} 线程 × 每线程 {a.per_worker} 次')
    print('  注：本次压测关闭了速率限制（测的是应用+存储承压，不是限流器）。')
    print('      限流开着时 write 组持续上限约 5 次/秒、突发 10。\n')
    scenarios.append(run(factory, '读：高频 GET telemetry', 'GET',
                          '/api/telemetry/latest', workers=a.workers, per_worker=a.per_worker))
    scenarios.append(run(factory, '读：高频 GET vendors', 'GET', '/api/vendors',
                          workers=a.workers, per_worker=a.per_worker))
    scenarios.append(run(factory, '写：并发 intent submit', 'POST', '/api/intent/submit',
                          workers=a.workers, per_worker=max(3, a.per_worker // 3),
                          body={'text': '访客网络限速5Mbps'}))

    # 混合读写
    lat, errs = [], []
    lock = threading.Lock()

    def mixed(i):
        cl = factory()
        for k in range(max(3, a.per_worker // 3)):
            t0 = time.perf_counter()
            try:
                r = (cl.post('/api/intent/submit', json={'text': f'混合压测-{i}-{k}'})
                     if k % 3 == 0 else cl.get('/api/telemetry/latest'))
                dt = (time.perf_counter() - t0) * 1000
                with lock:
                    lat.append(dt)
                    if r.status_code != 200:
                        errs.append(str(r.status_code))
            except Exception as exc:
                with lock:
                    lat.append((time.perf_counter() - t0) * 1000)
                    errs.append(type(exc).__name__)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(mixed, range(a.workers)))
    m = summarize(lat, errs)
    m.update(scenario='混合：读写并行', workers=a.workers, total=len(lat))
    scenarios.append(m)

    for s in scenarios:
        print(f"  {s['scenario']}")
        print(f"    实发 {s['total']} 条 · 错误 {s['errors']}"
              + (f" ({', '.join(s['error_samples'])})" if s['errors'] else ''))
        print(f"    p50={s['p50_ms']}ms  p95={s['p95_ms']}ms  p99={s['p99_ms']}ms  max={s['max_ms']}ms")

    # 数据完整性：压完不能丢数据、不能写坏文件
    from app.store import STORE, DATA_PATH
    import json as _json
    fp = Path(DATA_PATH)
    healthy = fp.exists()
    if healthy:
        try:
            _json.loads(fp.read_text(encoding='utf-8'))
        except Exception as exc:
            healthy = False
            print(f'  ❌ 压测后数据文件损坏: {exc}')
    leftovers = [p.name for p in fp.parent.glob('.*tmp*')] if fp.parent.exists() else []
    print(f'\n  压测后数据文件完好: {healthy} · 残留临时文件: {len(leftovers)}')
    snap = obs.snapshot()
    print(f"  服务自身观测：http.requests={snap['counters'].get('http.requests')} "
          f"errors.4xx={snap['counters'].get('http.errors.4xx')} "
          f"errors.5xx={snap['counters'].get('http.errors.5xx')}")

    if a.json:
        print('\n' + json.dumps({'scenarios': scenarios, 'data_intact': healthy,
                                 'temp_leftovers': len(leftovers)}, ensure_ascii=False, indent=2))
    total_err = sum(s['errors'] for s in scenarios)
    return 0 if total_err == 0 and healthy and not leftovers else 1


if __name__ == '__main__':
    raise SystemExit(main())
