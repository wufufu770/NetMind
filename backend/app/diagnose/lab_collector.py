"""真实遥测采集。

对照 `core/telemetry.py` 的模拟器：那里的 sample() 返回硬编码常量，
congestion 恒为 68ms/1.8% 丢包，link_down 恒为 999ms/100% 丢包——
不测任何东西，heal() 也只是把 fault 改回 normal 再采一次，于是「处置成功」是必然的。

本模块从真容器采真 ICMP 回包，把原文解析成测量值。测量即证据：
丢包从报文统计算，延迟从逐包 time= 字段算，不推断、不补默认值。

纯函数与 I/O 分离：parse_ping 是纯的，可对着 tests/fixtures/lab/ 下的
真实抓取文本做回归；collect_lab_snapshot 才碰 docker。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..schemas import TelemetrySnapshot

LOSS_RE = re.compile(r'(\d+)\s+packets transmitted,\s*(\d+)\s*(?:packets )?received,\s*([\d.]+)%\s*packet loss')
RTT_RE = re.compile(r'round-trip\s+min/avg/max\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)\s*ms')
PER_PKT_RE = re.compile(r'time=([\d.]+)\s*ms')
SEQ_RE = re.compile(r'seq=(\d+)')


def parse_ping(text: str) -> dict:
    """把 ping 输出解析成测量值。缺字段就缺，不猜。

    真实场景会缺字段：链路全断时根本没有 round-trip 行（0 回包），
    此时 rtt_* 为 None 而不是 0——0 会被误读成「延迟为零的健康链路」。

    丢包以**报文计数**为准，不用 ping 自报的百分比：自报值在丢包率高时
    会向上取整（10 发 9 收自报 0%），按计数算才准。
    """
    m = LOSS_RE.search(text)
    transmitted = int(m.group(1)) if m else 0
    received = int(m.group(2)) if m else 0
    declared = float(m.group(3)) / 100.0 if m else None
    if transmitted > 0:
        loss = (transmitted - received) / transmitted
    else:
        loss = declared

    r = RTT_RE.search(text)
    rtt_min, rtt_avg, rtt_max = (float(r.group(1)), float(r.group(2)), float(r.group(3))) if r else (None, None, None)

    per_pkt = [float(x) for x in PER_PKT_RE.findall(text)]
    seqs = [int(x) for x in SEQ_RE.findall(text)]

    return {
        'transmitted': transmitted,
        'received': received,
        'loss_ratio': loss,
        'declared_loss': declared,
        'rtt_min_ms': rtt_min,
        'rtt_avg_ms': rtt_avg,
        'rtt_max_ms': rtt_max,
        'per_packet_ms': per_pkt,
        'seq_seen': seqs,
        'has_rtt': r is not None,
    }


def classify(measured: dict) -> str:
    """按测量值给状态。不参考任何预设标签。

    阈值取自可解释的分界，不是拟合出来的：全断、可用但严重劣化、可用且正常。
    """
    if measured['transmitted'] == 0:
        return 'unmeasured'
    loss = measured['loss_ratio']
    rtt = measured['rtt_avg_ms']
    if loss is not None and loss >= 0.9:
        return 'link_down'
    if rtt is None:
        return 'partial_loss'          # 有丢包但拿不到 RTT（丢包到统计不出一半回包）
    if rtt > 100:
        return 'congested'
    return 'healthy'


def to_snapshot(measured: dict, source: str = 'lab') -> TelemetrySnapshot:
    """测量值 → 快照。丢包即告警依据；延迟缺失不填 0。"""
    state = classify(measured)
    return TelemetrySnapshot(
        # 缺测就留空。此前对缺失的 rtt/loss 填 999.0 / 1.0 这两个哨兵值，
        # 下游 diagnose() 读到「999ms + 100% 丢包」就判 link_down——
        # **把「没测到」变成了「测到断链」**，可能对一台其实正常的设备下发处置。
        # 带宽同理：没测带宽就填 0.0 也同样是编一个数。
        latency_ms=measured['rtt_avg_ms'],
        packet_loss=measured['loss_ratio'],
        throughput_mbps=None,                    # 尚未做带宽测量；不编造
        alert=state != 'healthy',
        source=source,
    )


def collect_lab_snapshot(count: int = 10, target: str = '192.168.3.1', client: str = 'nm-client1') -> dict:
    """I/O 边界：真的调 docker 真的 ping。失败抛错，不返回假数据。"""
    cmd = ['docker', 'exec', client, 'ping', '-c', str(count), '-i', '0.2', '-W', '2', target]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and not LOSS_RE.search(r.stdout or ''):
        raise RuntimeError(f'lab probe failed: {(r.stderr or r.stdout).strip()[:200]}')
    measured = parse_ping(r.stdout)
    measured['state'] = classify(measured)
    return measured


def load_fixture(name: str) -> dict:
    """读 tests/fixtures/lab/ 下抓好的真实报文，用于回归。"""
    p = Path(__file__).resolve().parents[3] / 'tests' / 'fixtures' / 'lab' / f'ping-{name}.txt'
    text = p.read_text(encoding='utf-8')
    measured = parse_ping(text)
    measured['state'] = classify(measured)
    measured['fixture'] = p.name
    return measured
