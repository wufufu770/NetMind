from __future__ import annotations
from ..schemas import BenchmarkResult
from .workflow import ORCHESTRATOR

BENCHMARK_INTENTS=[
    '今晚8点保障答辩视频会议，延迟低于50ms，访客网络限速5Mbps',
    '访客网络限速5Mbps，并禁止访问实验室服务器',
    '实验室网络隔离，只允许教师终端访问实验服务器',
    '凌晨2点到4点保障数据库备份链路，带宽不低于50Mbps',
    '考试期间禁止学生终端访问外网，只允许访问考试服务器',
    '保障内部 VoIP 通话低延迟，抖动低于10ms',
]

def run_benchmark():
    results=[ORCHESTRATOR.run_closed_loop(text, dry_run=True) for text in BENCHMARK_INTENTS]
    total=len(results)
    return BenchmarkResult(
        total=total,
        parsed=sum(1 for r in results if r.intent is not None),
        planned=sum(1 for r in results if r.policy_set is not None),
        verified=sum(1 for r in results if r.verification is not None),
        deployed=sum(1 for r in results if any(s.agent=='DeployAgent' for s in r.steps)),
        healed=sum(1 for r in results if r.healing is not None),
        success_rate=sum(1 for r in results if r.status in {'success','warning'} or str(r.status) in {'Status.success','Status.warning'})/total,
        average_steps=sum(len(r.steps) for r in results)/total,
    )
