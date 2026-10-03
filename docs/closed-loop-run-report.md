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
| S0 基线 | 无 | RTT 0.093ms / 丢包 0.0 | — | — | — |
| S1 拥塞 | `tc netem delay 120ms loss 8%`（r1 出口） | RTT 120.288ms / 丢包 0.1 | RTT 0.12ms / 丢包 0.0 | ✅ True | ✅ True |
| S2 断链 | `r2 eth1 link down` | RTT 999.0ms / 丢包 1.0 | RTT 0.118ms / 丢包 0.0 | ✅ True | ✅ True |
| S3 **反例** | 同 S1，但处置动作为**空操作** | RTT 120.281ms | RTT 120.345ms | ❌ **False** | ✅ True |

原始数据：`tests/fixtures/lab/closed-loop-run.json`

## 走真实 SSH 下发的自愈（`TelemetryService.heal()`）

上表的 S1/S2 走的是 `diagnose/closed_loop.py` 的闭环。这一节是另一条路径：
主链路的 `TelemetryService.heal()` —— 生成命令 → 过安全门 → **TransactionManager
经 SSH 真下发** → 重测对比。注入点、探测点、下发点同为 client2，所以改善只可能
来自这条命令，不来自别处。

复现（容器 `nm-client2` 需带 `tc` 与 NOPASSWD sudo，见 `scripts/lab.sh up`）：

```bash
# 环境：driver 指向可处置主机 client2，探测从 client2 打 dev1
NETMIND_DRIVER=ssh NETMIND_SSH_HOST=192.168.1.11 NETMIND_SSH_PORT=2222 \
NETMIND_SSH_USERNAME=netmind NETMIND_SSH_PASSWORD=netmind123 \
NETMIND_ENABLE_REAL_COMMANDS=true NETMIND_SUDO=true \
NETMIND_PROBE_TARGET=192.168.1.30 .venv/bin/python scripts/verify_heal.py
```

| 步骤 | 观测 | 来源 |
|---|---|---|
| 注入拥塞 | `qdisc netem 801f: root ... delay 150ms loss 10%` | 设备侧 `tc qdisc show` |
| 探测 | 延迟 150.277ms / 丢包 0.1 / `source=real` | 主链路真探测 |
| 诊断 | `congestion`，置信度 0.394 | 证据 `{packet_loss:0.1, latency_ms:150.277}` |
| 生成并下发 | `tc qdisc del dev eth0 root`，`mode=real` | TransactionManager 经 SSH |
| 设备侧读回 | `qdisc noqueue 0: root refcnt 2` | 设备侧 `tc qdisc show` |
| 重测 | 延迟 0.203ms / 丢包 0.0 | 主链路真探测 |

结果 `success=True, verified=True`。设备侧 qdisc 从 `netem` 变回 `noqueue` 是独立于
NetMind 自报的第三份证据——命令确实在设备上执行了，不是本地变量改了改。

**这次跑测本身抓到的一个真问题**：第一次跑时探测静默降级成了模拟器
（`source=simulated`），而脚本照样输出了一个「看起来正常」的 0.203ms 结论。
原因是 env 名写错（`NETMIND_SSH_USER` vs 实际认的 `NETMIND_SSH_USERNAME`）。
**这正是诚实表存在的理由**——快照自带 `source`，脚本才能发现自己测的是模拟器。
若当初 `source` 是硬编码常数，这个假结论会一路写进报告。

## 真实路由表（zebra 输出，非推断）

```
K>* 0.0.0.0/0      [0/0] via 192.168.2.1, eth1        r1 默认路由
K>* 192.168.3.0/24  [0/0] via 192.168.2.3, eth1        r1 经 r2 到远端段
C>* 192.168.1.0/24 is directly connected, eth0
C>* 192.168.2.0/24 is directly connected, eth1
C>* 192.168.3.0/24 is directly connected, eth1        r2 的远端段
```

原文见 `tests/fixtures/lab/frr-routing-table.txt` 与 `frr-routing-table-r1.txt`，
采集命令 `scripts/lab.sh measure` 的 D 段。

**采这段数据时踩到的坑值得记**：zebra 需要 `--cap-add=SYS_ADMIN` 才能起来。
缺了它，`watchfrr` 照常拉起 `staticd`，但 zebra 进程不出现——`/var/run/frr/` 下
只有 `staticd.vty` 没有 `zebra.vty`，而 `vtysh` 只报一句「zebra is not running」，
不告诉你真正原因是权限。真因藏在 `privs_init: initial cap_set_proc failed:
Operation not permitted` 里。**表层报错与真因不在一处**，只信表层会一直查错方向。

## 下发后无改善时的真回滚

上一节验证「处置奏效」的那一半。这一节验另一半：**处置没奏效时，系统会撤销它**。

此前这里完全没有实现——`heal()` 在重测发现没改善后，只是把 `success` 报成
`False` 就结束了，坏变更留在设备上，而 docstring 写着「触发回滚」。
`transaction.py` 里的回滚是 `deploy()` 的内部闭包，部署一旦成功返回，
**再没有任何入口能撤销它**。最该撤销的场景反而是唯一撤不掉的。

```bash
scripts/lab.sh up
NETMIND_DRIVER=ssh NETMIND_SSH_HOST=192.168.1.11 NETMIND_SSH_PORT=2222 \
NETMIND_SSH_USERNAME=netmind NETMIND_SSH_PASSWORD=netmind123 \
NETMIND_ENABLE_REAL_COMMANDS=true NETMIND_SUDO=true \
NETMIND_PROBE_TARGET=192.168.1.30 .venv/bin/python scripts/verify_heal.py --scenario rollback
```

| 步骤 | 观测 | 来源 |
|---|---|---|
| 起点 | `qdisc noqueue 0: root refcnt 2` | 设备侧读回 |
| 探测 | 0.134ms / 丢包 0.0 / `source=real` | 主链路真探测 |
| 下发 | `tc qdisc add dev eth0 root netem rate 5mbit`，`mode=real`、`applied=True` | TransactionManager 经 SSH |
| 重测 | 0.125 → 0.628ms（限速对 ICMP 往返几乎无影响，所以**没改善**） | 主链路真探测 |
| 判定 | `capability=inverse` `attempted=True` `rolled_back=True` `complete=True` | 回滚报告 |
| 设备侧读回 | `qdisc noqueue 0: root refcnt 2` | 设备侧读回 |

限速被真实撤销，设备回到起点。回滚效果能在设备上直接读回，是因为
`anomaly_traffic` 的处置是**加**一条限速、逆操作就是删掉它，等量可逆。

**`congestion` 撤不回来，这是实话。** 它的处置是删掉设备原有的队列整形；
要恢复得知道原来是什么（netem 延迟？限速？prio 队列？），而处置前没采这个状态。
早先代码把 `tc qdisc show` 塞进 `rollback_commands`，执行方跑完就报
`rolled_back=True`——在一件都没撤销的情况下说「已回滚」。现在回滚列表里只放
**真逆操作**，只读检查降级为诊断命令，撤不回来时报告里明写「无法自动回滚」。

### 顺带补上的一道安全门

`ip route del` 属危险操作，安全门在 `allow_dangerous` 路径上**仍要求归属证明**
（此前只认流表 cookie）。这意味着 `link_down` 的回滚原本永远会被自己拦下。
按流表 cookie 的同一原则补了路由登记：只有本系统 `ip route add` 下去、
且规格完全一致的路由才允许删除——命令文本可伪造，登记不可。

反向测试：未登记的路由删除请求仍被拒（`test_rollback_without_ownership_is_refused`）。



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
  路由表是 zebra 的真实输出（`tests/fixtures/lab/frr-routing-table-r1.txt`），但只有
  直连与静态路由，**没有** OSPF/BGP 等动态协议的邻居与收敛数据。
- **「处置」= 清除实验台注入的故障**，不是「自动修复真实网络故障」。它证明的是闭环
  机制本身不撒谎，**不**证明 NetMind 能修好真实网络。
- **处置路径验过两条，剩下两条没验**：`congestion`（清整形）与 `anomaly_traffic`
  （加限速）已在设备上实跑，含各自的回滚行为。`link_down`（下发 `ip route add`）
  的方案生成、安全门与路由归属登记有测试覆盖，但**没有**在设备上实跑过。
  `config_error` 刻意不给自动处置——`ovs-ofctl del-flows` 属危险操作，只放行带
  NetMind cookie 的流表，拿不到归属证明就不该自动动手。
- **回滚只在单设备单接口上验过，且只有可逆处置能验**：逆操作要等量可撤销才谈得上
  回滚，所以 `congestion` 的回滚**结构性不可用**（删了原有整形但未记录参数）。
  **不能**据此声称「任何处置都能自动撤销」。
- **单台设备、单接口、单方向**：自愈与回滚验证全部在 client2 的 eth0 上完成。
  **不能**据此声称多设备联动或路径切换正确。
- **样本量小**：每场景 10 个包（命令见上「复现」节），S1 的丢包率在不同轮次
  实测到 0% 与 10% 两种结果（netem 的随机性，原始数据见
  `tests/fixtures/lab/throughput-real.json`），**不能**拿单次数字做 SLA 承诺。

## 与诚实表的对应

| 诚实表条目 | 本报告的证据 |
|---|---|
| Lab data collection | S0–S3 全部来自活实验台实测 |
| Post-apply verification | ✅ 已实现——S1/S2 的 `verified=True` 即重测完成 |
| Healing action | ✅ Real（机制层）—— 处置是真命令，过安全门后经 SSH 真下发并重测；`congestion` 与 `anomaly_traffic` 路径在真实设备端到端跑通，见上两节。⚠️ `link_down` 路径未在设备实跑，真实生产故障未验证 |
| Post-verify rollback | ✅ Real（机制层）—— 下发成功但重测无改善时真调 `rollback()` 撤销，`anomaly_traffic` 路径已在设备上读回确认限速被撤掉。⚠️ `congestion` 结构性不可回滚，如实报「无法自动回滚」 |
| Diagnosis thresholds | ⚠️ 阈值为单一拓扑标定；带宽判定需基线，无基线时跳过 |
| Routing state | ✅ Real — zebra 真实路由表（仅直连+静态，无动态协议） |
