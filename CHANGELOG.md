# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]
### Added
- 前端展示层的取值决策抽到 `frontend/src/lib/display.js`（`frontend/src/lib/auth.js`
  同轮新增）：指标取值、健康分、健康环、验证摘要、置信度——都是「用户被告知什么」
  的决策点，此前散在 `App.jsx` 里一行测试都没有。补 20 个用例，前端 12→30

### Fixed
- **`/api/system/status` 的三个字段从不是测出来的**。`healthy` / `driver` / `model_online`
  从未被任何代码赋值，全吃 schema 默认值——于是这个探活与运维真正会看的接口恒返回
  `healthy=true` / `driver=simulation` / `model_online=true`：配了 SSH 驱动、模型离线、
  压根没采到数据，都照报「健康」。现四个字段各自有出处，并新增 `telemetry_source`
  与 `auth_mode`
- **只读用户在界面上看不出自己是只读**。服务端早已按档位拦写操作（403），
  但按钮照常可点，点了才知道不行——那比没有只读角色更让人困惑。
  现读 `/api/system/status` 的 `auth_mode` 识别身份并给出明确提示

- **配了 `NETMIND_ADMIN_TOKEN` 之后网页面板全线 401**（实测确认）。前端 `request()`
  发的是 `X-NetMind-Admin` 自定义头，而后端只读 `Authorization: Bearer`——
  于是 `docs/DEPLOY.md` 第 1 节推荐的部署方式下，整个界面不可用。
  改为发标准头，并把凭据逻辑抽到 `frontend/src/lib/auth.js`（8 个新测试）
- **一份写死的默认凭据**。前端此前有个兜底的 `'netmind-local-admin'`。
  后端不认它所以只是无效字符串，但它离「一份所有人都知道的固定口令」只差
  后端哪天认了这个头。现在取不到凭据就是取不到
- 401 与 403 的提示不再混成一句「请求失败」：前者是没给或给错凭据，
  后者是凭据有效但角色不够，提示里会分别告诉用户该配什么、该找谁申请


## [0.2.0] - 2026-10-03

这一版的重点不是加功能，是**把「说自己能做」的地方逐条改成真的**。下面每条
「Fixed」在修复前都曾是对外可见的错误行为——文档这么写、界面这么显示、
或者门禁这么绿。技术类细节见 `docs/closed-loop-run-report.md`、
`docs/commercial-readiness-audit.md` 与 `docs/DEPLOY.md`。

### Added

**自愈闭环（真动作）**
- 自愈处置是真命令而非中文描述串：过安全门 → TransactionManager 下发 → 重测对比
  （`core/remediation.py`）。`congestion` 路径已在真实设备端到端跑通
  （150.277ms→0.203ms，设备侧 qdisc `netem`→`noqueue` 读回确认）
- 处置后重测验证，如实区分「干跑没下发 / 设备拒绝执行 / 下发了没改善」
- `TransactionManager.rollback()` 公开入口：下发成功但重测无改善时真去撤销。
  `anomaly_traffic` 路径已在真实设备验证（下发限速→无改善→设备侧读回确认已撤销）
- 回滚能力分三级（`inverse` 真逆操作 / `inspect` 只读检查 / `none`），
  只读命令不再进回滚列表——否则会在一件都没撤销时报 `rolled_back=True`
- 路由归属登记：`ip route del` 没有 cookie 可挂，按流表 cookie 的同一原则
  用「本系统 `ip route add` 下去且规格完全一致」的登记做归属证明。
  命令文本可伪造，登记不可
- 自愈两道护栏（`core/heal_guard.py`）：`NETMIND_HEAL_IFACE` 不配则自动处置关闭
  （**不猜接口**——猜错就是对错误的口下手）；连续失败按 (诊断类型, 接口) 记账、
  落盘、默认上限 3，触顶停止自动动作转人工。成功清零，干跑不消耗预算
- 真实网络实验台 `scripts/lab.sh`：双 FRR + 客户端，布出真两跳 L3 路径，
  可注入 netem 拥塞与断链。`scripts/verify_heal.py` 提供可复现的自愈与回滚验证

**真实数据与可观测性**
- 主链路接真实遥测：`TELEMETRY.sample()` 优先真探测，经已建立的 SSH 连接在
  **被监控设备上**发起 ICMP（本地 ping 只能测到本地网卡，不是网络运维的真实测法）
- 遥测来源可查：`TELEMETRY.provenance()` 回答「这个数字是测的还是模拟的」
- 真实路由数据：FRR/zebra 真实路由表 fixture（`frr-routing-table*.txt`）
- 真实设备只读采集走 netmiko 直连（`diagnose/linux_collect.py`）——napalm 5.2
  核心驱不了这类设备，而实验台拓扑正是这类型
- 真实采集 fixture `tests/fixtures/lab/live-collection.json`（真 SSH 端点，
  含正例与两个反例）
- 自身可观测性：`/healthz` + `/metrics`（p50/p95/p99 分端点、错误计数）
- 变更提案（config-diff）：下发前把「将改什么」显式摊开，危险项排前并标注
  必须走审批流，输出可评审的 Markdown（`core/config_diff.py`）

**部署与数据**
- `docs/DEPLOY.md`：自托管部署指南。先决定访问边界 → 起服务 → **必须单 worker**
  → 数据在哪怎么保 → 对外暴露要点 → 探活 → 接真实设备 → **开启自动处置** →
  故障排查表。每一节的关键命令都实测过
- `scripts/data_ops.py`：数据保全命令 `backup` / `restore` / `verify` / `list` /
  `drill`。`drill` 是恢复演练——备份 → 故意破坏 → 恢复 → 校验内容逐字节一致
- `scripts/load_test.py`：HTTP 层并发压测（读/写/混合/鉴权四类），输出
  p50/p95/p99 与错误数，并校验压测后数据文件完好、零临时残留
- 前端首次有测试：`frontend/src/lib/format.js` + 12 个用例（node 内置 runner，
  零依赖）。此前 `package.json` 连 test 脚本都没有

**治理与供应链**
- `LICENSE`（MIT 文件此前缺失，尽管 README 与 pyproject 均声明 MIT）
- 无限迭代循环协议：BUILD → TEST → IMPROVE → PLAN → STATE，每轮一个可验证增量，
  门禁声明失败退路，状态落盘保证永远有下一步（`.netmind-loop/`）
- 去 AI 味密度门：客户可见面按密度检测空洞套话、无源数字、元评论、
  装饰性 emoji、过度格式化（`scripts/copy_lint.py`）
- `scripts/ci_audit.py`：把 ci.yml 里每条可实跑的命令真跑一遍
- 厂商能力矩阵（`diagnose/vendor_matrix.py` + `GET /api/vendors`、`/api/vendors.md`）。
  每家厂商带**验证等级**：verified / declared / blocked，README 不再自述厂商清单
- `netmind audit` 只读巡检 v1
- CI 新增 `loop-gates` 与 `supply-chain` job；CodeQL（python + javascript-typescript）
- CI 的 `frontend-build` job 补上 `npm test`（此前只 build 不 test）
- `docker-compose.yml` 补注释说明「token 留空 = 仅本机可访问」是安全默认值
- Dependabot 覆盖 pip / npm / github-actions 三条
- `CLA.md` 草案；`CONTRIBUTING.md` 第 5 条：营销面可核查律
- 门禁从 8 条增至 28 条，全部行为判定，不做源码文本匹配

### Fixed

**谎报类（对外可见的错误行为）**
- **自愈恒报成功**。`HealingReport.success` 此前默认值 `True` 且全仓无代码赋值；
  `telemetry.heal()` 把 `fault` 改回 normal 再采一次样就算「处置成功」——
  与是否真做了事无关。现 `success` 只能由实测前后对比推出
- **主工作流的 HealingAgent 永远动不了**。`workflow.py` 调 `heal(diag)` 不传
  `iface`，而 `build()` 缺 `iface` 就抛 `RemediationUnavailable`，每次都走
  「无需处置」；且那一行无论返回什么都记 `Status.success`——审计里看过去
  就是「自愈成功了」
- **`SSHDriver.execute()` 无条件 `success=True`**。实测 `tc: command not found`
  也报成功，于是「已真下发」在命令根本没跑时同样成立。改为取远端退出码，
  拿不到标记时不猜成功
- **`/api/dashboard` 的数字全是路由里的字面量**：`sla` 恒为 98、
  `active_intents` 恒为 2，配三条固定风险文案和两个编造的意图名。
  现由 `core/dashboard.py` 从真实状态推导；SLA 达成率没有约定目标就返回
  `null` 并写明原因，前端随之显示 `--`（此前它在 sla 为空时用丢包率反推 96/82）
- **`/api/telemetry/predict-sla` 整个是坏的**。后端是 `GET` 无请求体、门槛写死
  50ms，而前端一直 `POST` 并传了完整目标——实测 POST 直接 405；字段名
  `achievable` 对不上前端的 `feasible`，toast 恒走「不可行」分支。
  现按调用方给的目标判定并返回 `target_used` 与 `breaches`；不给目标则返回
  `feasible: null`，不替用户决定什么叫达标
- **`/api/system/ai-recovery-review` 什么都没比较**却恒返回「复核完成、无冲突」。
  现真跑规则引擎再比对，判不了的记入 `undecidable` 并强制
  `indeterminate`/`partial` 结论
- **前端三处编造常量**：下发/回滚/回滚计划结果里的 `sla_feasible: true` 与
  `sla_confidence: 1`——部署结果里本就没有 SLA 依据，会把「未知」显示成
  「可行 100%」
- **诊断置信度是编造的常量**。link_down/congestion/anomaly_traffic 硬编码
  .98/.92/.88，与证据无关——实验台实测同样 120ms 延迟（`tests/fixtures/lab/throughput-real.json`），
  带宽 18.66Mbps 与 4.01Mbps 的置信度完全相同。现由证据强度、样本量、是否有独立佐证推导
- **压测报告了一个没发生过的压测量**。只发了 `per_worker` 条，打印的却是
  `workers × per_worker`。现改为实发实报并断言
- **`/ws/events` 连接泄漏**。只捕 `WebSocketDisconnect`，发送过程中抛错时连接
  永远留在 `WS` 列表里——而 `/api/system/status` 正是拿 `len(WS)` 当
  「在线客户端数」报的，长跑进程里这个数字会越走越偏且不报错。改用 `finally`
- **回滚集包含从未下发的变更**。策略 b 首条命令失败时，策略 b（一条都没下发
  成功）也跟着被回滚。现回滚只覆盖「已成功下发」的命令
- **cookie 登记后永不释放**。回滚完成了 cookie 还留着，等于给后续特权回滚留了
  一条不需要重新下发的路
- **首条命令就被拦时误报「已回滚」**。什么都没执行却报 `rolled_back=True`
- **一个测试把假象写成了契约**：`test_core.py::test_fault_heal` 此前断言
  `heal['success']` 为真——反过来阻止修复。已改为断言「模拟路径必须承认未验证」

**正确性类**
- **「5%~90% 丢包」被判成 link_down**（实测报文 `tests/fixtures/lab/ping-congestion.txt`，
  回归 `backend/tests/test_real_telemetry.py`）。模拟器拥塞态丢包只有 1.8%，永远落在
  阈值下，该分支在模拟数据下**从未被执行过**——真实探测一上来就是 120ms + 10% 丢包，当场判错
- **拥塞判定把延迟与带宽绑死**。旧规则要求 `throughput_mbps < 60`，60 是绝对
  Mbps 阈值，高速链路上同条件会漏判。实验台实测：注入 120ms 延迟不限速时
  带宽 18.66Mbps，与健康态 21.08Mbps 接近——延迟升高与带宽受限是两件事
- **丢包以报文计数为准**，不再采信 ping 自报百分比（10 发 9 收自报 0%）
- **驱动映射三处错误**：① 映射到 napalm 不存在的 `'linux'`（所有 Linux/FRR
  设备必然 ModuleImportError，而错误被混进 errors 看起来像「设备连不上」）
  ② 兜底 `'else eos'` 把任何未知型号当 Arista 下命令 ③ `nokia`/`srl`
  在声明依赖下永远不可用
- **`ssh_driver.collect()` 把 netmiko 的 device_type 当 napalm 驱动名**
  （`linux` 在 napalm 里根本不存在）
- **采集回来的用法/报错文本被当作数据存储**。BusyBox 的 `ip` 不认 `-br`，
  会把用法说明打回来——「看起来有数据其实是报错」的污染最难发现
- **SBOM 步骤一直是红的，而且即使跑通也是错的**。`cyclonedx-py environment`
  扫的是 runner 环境而非项目依赖——**绿的 SBOM 比红的更危险**，采购会拿它当数。
  改为从声明文件生成
- **状态文件用自指字段 `head` 冒充当前 HEAD**。`save()` 发生在提交之前，
  永远指向「包含本状态的 commit 的上一个」，差一个是结构性的。改名为
  `based_on` 并写明语义
- **循环状态丢更新**。`loop.py` 读状态、三分钟后才写，期间任何写入都被旧快照
  静默覆盖（实测丢过一条 retro 且不报错）。改为 load 记 sha256、save 前比对
- **指标名实不符**：`tests_passed` 数的是 `def test_` 定义个数（parametrize 展开
  的用例没算进去，119 vs 实际 124），改用 pytest --collect-only 的权威结果并
  更名为 `tests_collected`；`cmd_metrics` 把 `gates_total` 写到顶层而打印的是
  `metrics.gates_total`，后者永远停在旧值（长期显示 15 而实际 16）
- **临时文件名会撞**。原实现固定用 `DATA_PATH.with_suffix('.tmp')`，同机两个
  进程同时保存会互相覆盖。改用 `tempfile.mkstemp`（此前是 `tmp.write_text()` +
  `tmp.replace()`）。中间试过「pid +
  thread_ident」拼名字，实测 10 个并发只产生 7 个不同名——CPython 的
  `get_ident()` 在线程结束后会回收复用，靠「同一 ident 不会并发」才安全，
  而那是巧合不是保证
- **`loop.py` 的 `status` / `gates` 是只读命令却每次都写 state.json**——
  查一眼状态就把已提交的快照弄脏
- **指标 `tests_passed` 名实不符**：数的是 `def test_` 定义个数，parametrize
  展开的用例没算进去。改用 pytest --collect-only 的权威结果
- **`scripts/lab.sh` 三个自埋的 bug**（此前一直手工敲等价 docker 命令，脚本
  本身从未被完整执行过）：缺 `--cap-add=SYS_ADMIN` 导致 zebra 静默起不来、
  客户端循环给两个容器都分配 `192.168.1.10`、`set -e` 碰上 100% 丢包的
  非零退出码当场退出——而「全断」恰恰是最该测出来的场景
- **`validate_project.py` 的路由提取在新版 FastAPI 上抛 `AttributeError`**
- **测试三处共享可变状态**（同一问题踩了三次）：数据文件跨运行累积、
  `importlib.reload` 造出新单例、后台自动保存线程与故障注入相撞
- **测试里调用 `monkeypatch.undo()` 会把 fixture 的补丁一并撤销**，看起来像
  功能坏了
- **故障注入点与实现脱节**：`save()` 已改用 `mkstemp + os.fdopen`，patch
  `builtins.open` 测到的不是「落盘失败」而是「什么都没发生」
- **`compactLabel` 的空值占位符从来没显示出来**（先取 `'--'` 再过替换规则，
  被吃成单个空格）
- 置信度折扣原先用「样本数减半」实现，只有 1 个样本时减半等于没减，折扣静默失效
- CI 审计初版会把 `loop-gates` 也跑一遍——门禁 → 审计 → 门禁 无限递归
- **依赖钉扎门此前只查 `>=` / `^` 浮动范围**（`deps-pinned-and-audited`）

**数据耐久性**
- **落盘缺 fsync**。rename 在同一文件系统内确实原子，但不 fsync 临时文件就
  rename，掉电后新目录项可能指向尚未落盘的数据；rename 本身也要 fsync 目录项
- **落盘失败被静默吞掉**。`mark_dirty` 与自动保存线程都是 `except: pass`。
  `save()` 现在返回成败并记进审计
- 崩溃残留的 .tmp 在启动时清理
- 速率限制的取值对合法批量操作偏紧 → 加 `NETMIND_RATE_LIMIT=off`；
  `init_from_env()` 在导入期改全局 → 改为每次判定时读

### Security

- 默认安全：**未配 token 时只有本机能访问**（远程一律 403），配了 token 后
  **所有方法包括 GET** 都要 `Authorization: Bearer <token>`。`X-Forwarded-For`
  默认不采信，需显式 `NETMIND_TRUST_PROXY`
- 危险操作按**命令语义**判定：`del-flows` / `mod-flows` / `iptables -F` /
  `link down` / `route del` / `addr del`，与设备名无关
- **回滚不绕过危险操作门**：`allow_dangerous=True` 仍要求归属证明（流表认
  cookie，路由认登记）
- 自动处置默认关闭，接口不猜；连续失败有上限并转人工
- 速率限制：按来源的进程内令牌桶（write 5/s·突发 10、read 50/s、public 5/s），
  超限 429 + `Retry-After`，**放在鉴权之前**——未授权的洪水请求同样要挡
- `POST /api/deploy/{id}/rollback` 真实执行回滚计划并逐命令校验；未部署返回 409
- 凭据以**掩码引用**存储（`secret_ref` 持久化为 `***`），真实密钥走运行时环境变量
- 依赖漏洞清零（`pip-audit` 与 `npm audit` 均 0）：fastapi 0.115.6→0.142.2
  （连同 starlette 0.41.3→1.7.0，原有 19 条 CVE）、python-dotenv 1.0.1→1.2.2、
  pytest 8.3.4→9.0.3、langgraph 浮动→1.2.12、vite 8.0.13→8.3.2
  （连带修掉 nanoid/postcss 高危）
- `SECURITY.md` 按实现重写：此前两处与实现不符（认证范围、回滚门），
  另补修复时效承诺与「尚不具备」的诚实声明（无 CVE 流程、无漏洞赏金、无签名产物）

### Changed

- 门禁退路体系：新增 `blocked` 状态与 `loop.py block`
- 死模块门禁由 `autofix` 降级为 `block`——移动代码需要语义判断
- `DeployResult.rollback_complete` 区分回滚全部成功与部分尝试
- tc 接口名严格策略仅限仿真；真实驱动接受标准接口名
- 厂商支持一律以 `GET /api/vendors` 矩阵为准，README 不再自述
- 移除死依赖 `recharts@3.8.1`（声明了但 `src/` 从未 import，白装白交付还扩大
  供应链面）；`vite` 从运行时依赖移入 devDependencies

### Removed

- `core/sqlite_store.py`：完整但从未接线的 23 行 KV 存储。零引用属死代码
- `backend/build` 构建产物出库

### Known gaps in 0.2.0

写在这里而不是藏起来：

- **多厂商只在 Linux/FRR 上真实验证过**。`cisco-ios` / `juniper-junos` /
  `arista-eos` 的镜像在本机拉不到，矩阵里停在 `declared`
- **路由数据只有直连与静态路由**，无 OSPF/BGP 等动态协议的邻居与收敛数据
- **`link_down` 处置路径未在设备上实跑**（方案生成、安全门与路由归属有测试覆盖）
- **`congestion` 处置没有可用的自动回滚**：删了设备原有整形但处置前没记录参数，
  造不出等价逆命令
- **无 RBAC**：持 admin token 者权限相同，无只读角色。对自托管单实例可接受，
  共享或多操作员部署不适用
- **限流与存储锁都只在进程内**：多 worker 会成倍放大限流阈值，且存储有丢写风险，
  故文档要求**必须单 worker**
- **压测走应用层**（TestClient），未过真实网络栈
- **无 CVE 流程、无漏洞赏金、无签名发布产物**

### 索引：这一版每条主张的核查入口

上面的条目都挂着可复现物。集中列一次，免得读者逐条翻。

**28 条门禁**（`python3 scripts/loop.py gates` 一次跑完，全部行为判定，
不做源码文本匹配）：

| 领域 | 门禁 id |
|---|---|
| 治理 | `license-present`、`loop-state-present`、`tests-green`、`validate-project`、`no-ai-smell` |
| 死代码 | `no-dead-module`、`no-dead-local`、`no-unused-declared-dependency` |
| 诚实性 | `no-fake-healing`、`real-data-not-faked`、`telemetry-not-guessed`、`dashboard-no-fabricated-numbers`、`security-doc-matches-behavior` |
| 自愈 | `rollback-on-no-improvement`、`healing-is-guarded` |
| 设备 | `vendor-matrix-is-authoritative`、`collection-not-guessed`、`routing-data-is-real` |
| 数据 | `data-durability-drill`、`load-test-no-loss`、`tests-are-reproducible` |
| 供应链 | `deps-pinned-and-audited`、`ci-steps-are-executable`、`sbom-covers-declared-deps`、`ci-security-gates`、`dependabot-present` |
| 前端 | `frontend-has-tests` |
| 状态 | `state-based-on-is-honest` |

**回归测试**（`pytest backend/tests/ -q`，250 例）按主题：

| 主题 | 文件 |
|---|---|
| 自愈与回滚 | `test_remediation.py`、`test_heal_guard.py`、`test_closed_loop.py`、`test_ssh_exec_result.py` |
| 遥测与真实数据 | `test_real_telemetry.py`、`test_real_lab.py`、`test_linux_collect.py`、`test_diagnose.py` |
| 安全门 | `test_security_gate_semantics.py`、`test_access_and_observability.py`、`test_honesty_guards.py` |
| 事务 | `test_transaction.py`、`test_policy_approval_flow.py` |
| 数据耐久性 | `test_store_durability.py`、`test_reports_store.py` |
| 限流 | `test_ratelimit.py` |
| 设备与厂商 | `test_driver_mapping.py`、`test_vendor_matrix.py`、`test_ssh_driver.py` |
| 面板与复核 | `test_dashboard_honesty.py`、`test_readiness_endpoints.py` |
| 其余 | `test_api_smoke.py`、`test_audit.py`、`test_config_diff.py`、`test_core.py`、`test_ai_workflow_integration.py`、`test_customization_workflows.py`、`test_langgraph_mcp_chat_config.py`、`test_smoke_packaging.py`、`test_runtime_intelligence.py`、`test_tools_credentials_reports.py` |

**实验台与脚本**：`scripts/lab.sh`（起实验台）、`scripts/lab.sh measure`
（采原始数据，含 FRR 守护进程状态与路由表）、`scripts/load_test.py`、
`scripts/data_ops.py`、`scripts/verify_heal.py`、`scripts/ci_audit.py`、
`scripts/copy_lint.py`

**真实数据 fixture**（`tests/fixtures/lab/`）：`ping-healthy.txt`、
`ping-congestion.txt`、`ping-link_down.txt`、`throughput-real.json`、
`live-collection.json`、`frr-routing-table.txt`、`frr-routing-table-r1.txt`、
`frr-interfaces.txt`、`r1-routes.txt`、`closed-loop-run.json`

**踩坑记录**：`docs/sbom-choice.md`（SBOM 为什么不能用 `environment` 子命令）、
`docs/closed-loop-run-report.md`（真闭环三场景 + 自愈 + 回滚，含「不能支撑的
主张」）、`docs/commercial-readiness-audit.md`（商用就绪度盘点）、
`docs/DEPLOY.md`（部署与自动处置开关）

**实现位置补充**：`diagnose/closed_loop.py`（实验台闭环）、
`diagnose/lab_adapter.py`（真调 tc / ip link / ping）、`diagnose/lab_collector.py`
（真实 ICMP 与网卡计数器）、`diagnose/drivers.py`（显式驱动映射，未知 kind 不兜底）、
`diagnose/linux_collect.py`（netmiko 直连）、`backend/requirements-drivers.txt`
（可选插件 `napalm-nokia` / `napalm-srl`）

**驱动映射**：`ios` / `iosxe` / `iosv` / `cat9k` → `ios`，
`nxos` / `nxos_ssh` → `nxos`，`iosxr` → `iosxr`

**删除项**：`backend/build` 与 `build/`（`.gitignore` 已加）

## [0.1.0] - 2026-08-22

First public release. The closed loop is real where it claims to be, and honestly labelled where it is not.
