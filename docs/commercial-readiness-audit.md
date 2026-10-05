# NetMind 商用就绪度审计

> ⚠️ **这是一份快照，不是当前状态。** 下文所有结论停在 2026-10-03 的
> `0b40287`。截至 2026-10-05 的推进：门禁从 18 条增到 **54** 条、后端测试从 0
> 增到 **347** 个、前端测试从 0 增到 **97** 个，并修掉了本报告点名的多个问题
> ——PDF 导出会静默丢掉全部汉字、安全审计在从未真正检查过的设备上报告「通过」、
> `diagnose --live` 对任何非 22 端口设备完全不可用、只读凭据从未真正拦住过写操作。
> **请勿把下文的 ❌ 当成今天的结论**；要看现状请读 README 的诚实表与 CHANGELOG
> （上面几个数字也随时在变，以现场门禁与测试输出为准）。保留原文不改，是为了
> 留下「当初到底差在哪」的基线。

审计时点：2026-10-03 · 分支 `feat/loop-protocol-r1` · HEAD `0b40287`（未推送）
方法：静态覆盖扫描 + 默认配置实测 + 门禁/矩阵全跑 + 对照 SECURITY.md 自认限制
口径：仓内证据可复现的结论才写进「已验证」；其余归入「未验证」或「缺失」。

---

## 一、结论先行

| 定位 | 能否 | 依据 |
|---|---|---|
| 单人自用工具 | ✅ 可以 | 真实下发/回滚/采集/闭环均已在真实容器上跑通 |
| 团队内部工具 | ⚠️ 接近，缺并发与备份验证 | 单 JSON 文件存储，无并发压测，无恢复演练 |
| **对外销售的商业产品** | ❌ **不行**，差 4 类硬门槛 | 见第四节 |

**一句话**：这个项目的「功能诚实度」已经很高（宣称基本都兑现了），但**工程成熟度还停在 alpha**——它能诚实地承认自己做不到什么，却还没有做到商业系统该有的隔离、限流、并发与恢复。

---

## 二、没有测试的部分

### 2.1 后端：20/55 源文件零测试触达（1005 行）

> 口径见文末「方法与边界」：粗粒度扫描，非行覆盖率。

按「测试文件里是否出现该模块名」粗粒度统计（有动态 import 时的漏判风险）：

| 文件 | 行数 | 备注 |
|---|---|---|
| `core/langgraph_compat.py` | 119 | LangGraph 兼容层，**项目的「可选降级」卖点就在这** |
| `core/tools_registry.py` | 97 | 工具注册表 |
| `routers/intents.py` | 91 | 意图入口路由 |
| `core/langgraph_adapter.py` | 75 | LangGraph 适配器 |
| `diagnose/lab_adapter.py` | 70 | 实验台适配（真跑过但无自动化回归） |
| `diagnose/llm_enhance.py` | 64 | LLM 增强 |
| `routers/templates_manage.py` | 59 | |
| `drivers/netconf_driver.py` | 56 | **NETCONF 驱动，零测试** |
| `routers/reports.py` | 54 | |
| **`core/transaction.py`** | **53** | **回滚管理器。** 唯一引用是 `test_honesty_guards.py:45-48`，那里注释明写「模拟 TransactionManager 行为」——它手工调 `STORE.register_flow_cookies` + `SECURITY.check`，**从未 import 或调用 TransactionManager 本身**。`deploy` / `rollback_plan` 两个方法被测试直接调用 0 处 |
| `routers/tools_mcp.py` | 52 | |
| `core/mcp_protocol.py` | 39 | MCP 协议层 |

> **`transaction.py` 是本次审计最刺眼的一条**。项目反复强调「rollback-safe」「未改善触发回滚」，而承载回滚语义的这个模块**没有任何自动化回归**——唯一提到它的地方是一条注释，测试里是「模拟」其行为而非调用它。真回滚只在 `closed_loop` 里通过 `SSHDriver.execute` 间接验过一次，事务管理本身的 `deploy` / `rollback_plan` 逻辑（部分回滚、失败回滚、幂等）零覆盖。

### 2.2 前端：App.jsx 1844 行，测试触达 0

> 当时的行数（`wc -l frontend/src/App.jsx`）。此后前端已抽出 `lib/`，现为 1704 行。

- 12 个前端用例只覆盖 `lib/format.js` 的 4 个纯函数（52 行）
- `App.jsx` 的 **43 个组件、61 处 useState、9 个页面**一行未测
- 前端唯一的自动门是 `npm run build`（能编译 ≠ 行为正确）

### 2.3 零压测 / 零负载 / 零并发测试

全仓 `grep -rlE 'load.?test|stress|locust|benchmark|concurrent'` 命中 0。

CI 全部在单进程下跑：`pytest -q`、一次 `npm run build`、一次 `npm audit`。**没有任何测试回答「10 个并发 intent 同时进来会怎样」**。

---

## 三、没有做完的部分

### 3.1 诚实表里仍是 ⚠️ 的两条

| 条目 | 实情 | 缺什么 |
|---|---|---|
| **Topology & telemetry data = Simulated generator** | `core/telemetry.py:36-39` 的 `sample()` 仍返回硬编码常量（congestion 恒 68ms/1.8%、link_down 恒 999ms/100%、normal 恒 23-26ms/82Mbps） | 真实采集只在 `diagnose/lab_collector.py` 这一条支路上跑通了，**主链路（workflow → telemetry → heal）仍然是假数据** |
| **Healing action 仅实验台验证** | 真实设备上验的是「下发一条命令 + 回滚它」，走的是 `SSHDriver.execute()` | 没验「自动诊断 → 自动修复」这条自动链。`HealingAgent` 的动作仍是字典里的中文描述串（`'启用备用路径并重新下发流表'`），不产生任何真实副作用 |

### 3.2 能力矩阵里 7/8 家未在真实设备验证

```
linux/frr      netmiko  verified   ← 唯一
其余 5 家      napalm   declared   ← 映射与依赖齐备，未在真实设备验过
nokia-sros/srl napalm   blocked    ← 需未安装的插件
```

原因：ceos / vyos / juniper 镜像在当前环境**全部拉不到**。这是环境限制，但商业化时客户会拿真设备来验。

### 3.3 未做的门禁

`dsh-compat` / `codeql` / `semgrep` 未配进 netmind 的 CI（d2d 侧有）。

---

## 四、商用的四类硬门槛（都缺）

### 门槛 1 · 默认配置下 API 完全裸奔

实测（`.env.example` 与 `docker-compose.yml` 默认均为 `NETMIND_ADMIN_TOKEN=` 空）：

```
不设 ADMIN_TOKEN → GET /api/telemetry/latest = 200
不设 ADMIN_TOKEN → GET /api/vendors        = 200
```

且 `main.py:19` 的门是 `if token and request.method not in {'GET','HEAD','OPTIONS'}` —— **GET 永远免认证**。任何人能访问该端口，就能读到全部拓扑、遥测、Agent 配置、workflow 历史。

凭据本身按 `SECURITY.md` 是掩码存储的（这一层是好的），但运行数据全裸。

> 商业部署的第一条要求是「默认安全」。这里是**默认不安全**。

### 门槛 2 · 无隔离、无 RBAC、无速率限制

`SECURITY.md` 自己写明：

> The HTTP API has no rate limiting or per-endpoint RBAC. Do not expose it to untrusted networks.

全仓无 `tenant` / `per_user` 概念——单文件全局 `STORE` 意味着**多客户之间没有任何数据边界**。商业 SaaS 里这是硬伤；即使是私有化交付，客户 IT 也会问「两个部门能不能各看各的」。

### 门槛 3 · 存储是单个 JSON 文件，并发与恢复未验

`store.py` 的模型：全量内存 dict + `RLock` + 2 秒防抖自动落盘 + `atexit` flush，上限 2000 日志 / 500 execution / 2000 遥测。

未验证的问题：
- 并发写是否会互相覆盖（RLock 只保护进程内）
- 进程被杀时最多丢 2 秒数据（可接受），但**落盘中途崩溃会不会写出半截 JSON？** 没有测过
- 2000 条遥测（`backend/app/store.py` 的 `MAX_TELEMETRY`）的滚动策略在真实负载下够不够
- 备份/恢复演练：没做过

### 门槛 4 · 无可观测性

项目自己有 `netmind audit` 巡检（这是它审计**网络设备**的能力），但**对自己这个服务的运行状况没有指标**——没有请求延迟分布、没有错误率、没有队列深度、没有自身健康检查。商业客户第一条 SLO 就问不出来。

---

## 五、要达到「可商用且稳定」，还差什么

按「必须先做」排序（括号内是估时，见下表逐项；1 人日 = 8h；**估时是判断不是测量**，无外部基准）：

| # | 事项 | 估时 | 验收 |
|---|---|---|---|
| **1** | **默认安全**：token 为空时拒绝启动或只允许 loopback；GET 也走认证 | 0.5d | 不设 token 时非本机请求拿 401 |
| **2** | **`transaction.py` 回归**：回滚语义（部分回滚、失败回滚、幂等）全覆盖 | 1d | ≥15 个用例，CI 跑 |
| **3** | **并发与恢复压测**：N 并发 intent + 强杀进程 + 恢复数据 | 1.5d | 有 `scripts/load_test.py` + 一份结果报告 |
| **4** | **主链路接真实遥测**：`telemetry.sample()` 在有 driver 时走真采集，无 driver 才降级 | 2-3d | 实验台上 workflow 主链路的数字来自真 ICMP |
| **5** | **HealingAgent 真动作**：把动作串落成可执行命令 + 真验证 | 2-3d | 靶场上「注入→自动诊断→自动修复→验证」跑通 |
| **6** | **多租户最小实现**：workspace 概念 + 按 workspace 过滤 | 3-5d | 两个 workspace 数据互不可见 |
| **7** | **RBAC + 速率限制**：至少三档角色 + 每端点限流 | 2-3d | SECURITY.md 那条限制被解除 |
| **8** | **自身可观测性**：/healthz、/metrics、请求延迟与错误率 | 1-2d | 客户能问出 p99 |
| **9** | **前端补测**：App.jsx 按页拆后补关键交互 | 2-3d | 关键页面有用例 |
| **10** | **供应链三件套**：`dsh-compat` / `codeql` / `semgrep` 进 CI | 0.5d | CI check-run 数 +3 |
| **11** | **真实多厂商验证**：拿到 ceos 或真设备后，把矩阵里 5 家 `declared` 升 `verified` | 依赖环境 | 矩阵可信度 |

**合计约 16–24 人日**（见上表逐项相加；纯估时，无外部基准；不含第 11 项的外部等待）。

**其中 1-3 是「不修就不能卖」的**（安全、核心模块回归、稳定性证据）；4-5 是「决定产品是否真有价值」；6-8 是「决定能不能卖给企业客户」；9-11 是「加分项」。

---

## 六、诚实的现状描述

NetMind 现在最准确的定位是：

> **一个功能完整、宣称诚实、工程成熟度停在 alpha 的单机网络运维工具。**
> 它的差异化不在功能数量，而在「宣称与实态对齐」这件事做得比同类好——
> 诚实表、门禁、跑测报告都在强制这件事。但它离「可以交给客户长期运行」还差
> 一段明确的工程距离，这段距离不在代码量上，在隔离、限流、并发证据与自身可观测性上。

**可以现在就开始卖的**：
- 私有化交付给单一团队、隔离网络、自担运维的技术型客户
- 卖「支持与咨询」而不是卖软件许可（软件当前状态撑不起 SLA 承诺）
- 定位成「工程师的意图驱动工具」而非「AIOps 平台」

**不该现在做的**：
- 公开 SaaS、多租户托管
- 承诺任何形式的 SLA
- 按设备数计价的企业授权（没有计费计量基础设施）

---

## 附：本次审计的方法与边界

- 覆盖率用「测试文件是否出现该模块名」粗粒度统计，**不是真正的行覆盖率**（未跑 coverage.py）；动态 import 场景可能低估
- 认证实测用的是 FastAPI TestClient，不经真实网络；反向代理后的行为未测
- 压测缺失是「grep 全仓无相关文件」的判断，未做「跑一下看看会不会崩」的实验
- 未修改任何文件，本报告为纯只读审计产物
