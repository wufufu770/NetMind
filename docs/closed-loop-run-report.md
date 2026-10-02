# 真闭环跑测报告

> 这份报告是**所有对外主张的唯一数字来源**。承 `CONTRIBUTING.md` 规则 5：客户可见的
> 每条主张必须挂一个能复现的东西。引本报告的数字时必须同时引下面的复现命令，
> 不能只引数字。
>
> 采集时间：2026-10-02 · 采集环境：docker 29.7.2，`frrouting/frr:latest`
> 数据原文：`tests/fixtures/lab/`

## 拓扑

```
client1(192.168.1.10) ──┐                     ┌── r2(192.168.2.3 / 192.168.3.1)
                        ├─ nm-sw1 192.168.1/24 ─┤
            r1(192.168.1.2 / 192.168.2.2) ─────┘
                                      └─ nm-r2net 192.168.2/24 ──┘
```

探测路径 `client1 → 192.168.3.1` 是**真两跳 L3**：client1 → r1 → 跨段网 → r2 → 远端段。
不经它拿不到真实延迟/丢包，遥测就只能靠硬编码常量。

## 复现

```bash
scripts/lab.sh up        # 起实验台并布线
scripts/lab.sh measure   # 采三态原始数据
.venv/bin/python -m pytest backend/tests/test_closed_loop.py -q   # 闭环回归
.venv/bin/python -m pytest backend/tests/test_real_lab.py -q       # 采集与诊断回归
```

## 结果

每个场景都是完整闭环：**注入真故障 → 真诊断 → 真处置 → 真重测 → 验证改善**。
「改善」不是声明，是重测对比的结论。

| 场景 | 注入 | 处置前（实测） | 处置后（实测） | success | verified |
|---|---|---|---|---|---|
| S0 基线 | 无 | RTT 0.133ms / 丢包 0.0 | — | — | — |
| S1 拥塞 | `tc netem delay 120ms loss 8%`（r1 出口） | RTT 120.288ms / 丢包 0.1 | RTT 0.12ms / 丢包 0.0 | ✅ True | ✅ True |
| S2 断链 | `r2 eth1 link down` | RTT 999.0ms / 丢包 1.0 | RTT 0.118ms / 丢包 0.0 | ✅ True | ✅ True |
| S3 **反例** | 同 S1，但处置动作为**空操作** | RTT 120.281ms | RTT 120.345ms | ❌ **False** | ✅ True |

原始数据：`tests/fixtures/lab/closed-loop-run.json`

## S3 是本报告最重要的一行

S3 注入的是和 S1 完全相同的真故障，处置动作却是空操作。结果：

```
success=False  verified=True
摘要：空操作（不实际处置）；未改善→已回滚：回滚也无效；
      重测对比：延迟 120.387→120.555ms、丢包 0.0→0.125（未改善，来源 lab）
      ↑ 原文见 tests/fixtures/lab/closed-loop-run.json
```

它**没有**报成功（原始数据见 `tests/fixtures/lab/closed-loop-run.json`）。这正是修复前 `core/telemetry.py::heal()` 做不到的事——那个函数把
`self.fault` 改回 `'normal'` 再采一次样，而样是硬编码常量，所以「处置后恢复正常」
是必然的；`HealingReport.success` 字段更是**默认 `True` 且从无任何代码给它赋值**。

修法：闭环的 `success` 只能由实测前后对比推出；`verified=False` 时 `success` 恒为
False；重测没改善则触发回滚并如实记录；探针挂了就记异常，不拿处置前的值冒充处置后的值。

## 本报告**不能**支撑的主张

诚实标注，避免过度解读：

- **只覆盖一条路径**：client1 → r2 一个方向、一个探测点、10 个包（见上表与
  `tests/fixtures/lab/closed-loop-run.json`）。**不能**据此声称「端到端时延」「多路径」
  「高可用」——这些都没测。
- **RTT 单位是毫秒且跨宿主机**：绝对值受宿主机调度影响，**不能**与生产网络的时延指标
  直接比较。可比的只有同环境下的相对变化——S1 的 120ms 是 `tc netem` 注入的
  （见上表与 `tests/fixtures/lab/throughput-real.json`），不是测出来的真实生产时延。
- **FRR 单厂商**：容器内跑的是 FRR，**没有**接 cisco-ios / juniper-junos / arista-eos。
  拓扑里 `zebra` 守护进程未起，**路由表数据本轮未采到**。
- **「处置」= 清除实验台注入的故障**，不是「自动修复真实网络故障」。它证明的是闭环
  机制本身不撒谎，**不**证明 NetMind 能修好真实网络。
- **样本量小**：每场景 10 个包（命令见上「复现」节），S1 的丢包率在不同轮次
  实测到 0% 与 10% 两种结果（netem 的随机性，原始数据见
  `tests/fixtures/lab/throughput-real.json`），**不能**拿单次数字做 SLA 承诺。

## 与诚实表的对应

| 诚实表条目 | 本报告的证据 |
|---|---|
| Lab data collection | S0–S3 全部来自活实验台实测 |
| Post-apply verification | ✅ 已实现——S1/S2 的 `verified=True` 即重测完成 |
| Healing action | ⚠️ 仅在实验台成立（清除注入故障），真实网络故障未验证 |
| Diagnosis thresholds | ⚠️ 阈值为单一拓扑标定；带宽判定需基线，无基线时跳过 |
