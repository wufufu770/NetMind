# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]
### Added
- 速率限制：按来源的进程内令牌桶（write 5/s·突发 10、read 50/s、public 5/s），
  补上 `SECURITY.md` 自认的缺口之一。超限 429 + `Retry-After`；**放在鉴权之前**——
  未授权的洪水请求同样要挡。`NETMIND_RATE_LIMIT=off` 供批量导入
- `test_ratelimit.py` 10 例：分组、窗口滑动、来源隔离、读松写紧、可关闭、
  超限 429 + Retry-After、限流先于鉴权、探活不被业务流量挤掉

- `docs/DEPLOY.md`：自托管部署指南。先决定访问边界 → 起服务 → **必须单 worker** →
  数据在哪怎么保 → 对外暴露要点 → 探活 → 接真实设备 → 故障排查表。
  每一节的关键命令都实测过

- `scripts/load_test.py`：HTTP 层并发压测（读/写/混合/鉴权四类），输出 p50/p95/p99 与错误数，
  并校验压测后数据文件完好、零临时残留。基线见 `docs/load-test-baseline.md`
- 门禁 `load-test-no-loss`：卡「零错误 + 数据不丢不坏」，**不卡延迟**（CI 上 p99 抖动大，
  拿它当门禁只会造假红）
- CI 加压测步骤

### Fixed
- **压测脚本报告了一个没发生过的压测量**。`ex.map(one, range(per_worker))` 只发了
  `per_worker` 条，打印的却是 `workers × per_worker` —— 算出来的不是观测到的。
  这正是本项目规则 2 禁止的事。现改为实发实报，并断言 `len(lat) == workers × per_worker`

- `test_transaction.py`：事务与回滚语义回归 10 例。此前该模块**零直接覆盖**——项目宣称
  最响的「可回滚」，测试最空的地方正是这里
- 门禁 `tests-are-reproducible`：全量测试连跑两次，通过数必须一致
- 门禁 `data-durability-drill`（上一轮）、`no-fake-healing` 等已在 CI 里

### Fixed
- **回滚集包含从未下发的变更**。原实现把整份 rollback_commands 在下发前就累积进去，
  于是策略 b 的首条命令失败时，策略 b（一条都没下发成功）也跟着被回滚。现在回滚只
  覆盖「已成功下发」的命令；两类失败区别对待——**被安全门拦下**确定没下发不回滚，
  **driver 报失败**可能已部分应用故保守回滚
- **cookie 登记后永不释放**。回滚完成了，cookie 还留在登记表里就等于给后续特权回滚
  留了一条不需要重新下发的路。新增 `release_flow_cookies()`，回滚结束即注销
- **首条命令就被拦时误报「已回滚」**。什么都没执行却报 rolled_back=True
- **测试三处共享可变状态**（同一问题踩了三次）：
  ① data 文件跨运行累积 ② `importlib.reload(store)` 造出新单例，transaction 往旧
     STORE 登记、security 惰性 import 拿到新 STORE 去查，cookie 明明登记了却查不到
  ③ STORE 的后台自动保存线程与故障注入的全局替换（os.replace/builtins.open）相撞，
     造成同代码连跑两次结果不同。三条都已在 conftest 治，并由新门禁锁住
- 测试里调用 `monkeypatch.undo()` 会把 fixture 打的补丁一并撤销——路径会退回
  conftest 的临时目录，看起来像功能坏了。故障注入改用局部 try/finally 恢复
- 故障注入点与实现脱节：`save()` 已改用 `tempfile.mkstemp + os.fdopen`，patch
  `builtins.open` 对它无效，测到的不是「落盘失败」而是「什么都没发生」。注入点改到
  `os.replace` / `os.fsync`——真正的原子步骤

- `scripts/data_ops.py`：数据保全命令 `backup` / `restore` / `verify` / `list` / `drill`。
  `drill` 是恢复演练——备份 → 故意破坏 → 恢复 → 校验内容逐字节一致。真出事时
  才用得到的东西，必须先演练过才知道能不能用
- 门禁 `data-durability-drill`：在 CI 里真跑一遍完整恢复流程，并验证损坏/不存在的
  恢复源会被拒绝（用坏数据盖好数据比不恢复更糟）
- CI 的 `loop-gates` job 增加数据耐久性演练与坏恢复源拒绝两步
- `test_store_durability.py`：13 个用例，覆盖半截写、并发保存、备份、恢复、容量上限

### Fixed
- **落盘缺 fsync**。原实现是 `tmp.write_text()` + `tmp.replace()`。rename 在同一
  文件系统内确实原子，但不 fsync 临时文件就 rename，掉电后新目录项可能指向尚未落盘的
  数据；rename 本身也要 fsync 目录项才算落盘。现在是：写临时 → fsync 文件 → rename
  → fsync 目录
- **临时文件名会撞**。原实现固定用 `DATA_PATH.with_suffix('.tmp')`，同机两个进程
  （服务端 + 一次 CLI 调用）同时保存会互相覆盖。改用 `tempfile.mkstemp`（O_EXCL
  原子保证唯一）。**中间试过「pid + thread_ident」拼名字，实测 10 个并发只产生
  7 个不同名——CPython 的 get_ident() 在线程结束后会回收复用**，那个方案靠
  「同一 ident 不会并发」才安全，而那是巧合不是保证
- **落盘失败被静默吞掉**。`mark_dirty` 与自动保存线程都是 `except: pass`，数据丢了
  没人知道。`save()` 现在返回成败，失败会记进审计日志并清理临时文件；自动保存连续
  失败 3 次会写一条 error 日志
- 崩溃残留的 .tmp 会在启动时清理（正常路径自己会清，只有 SIGKILL/掉电才留）

- `docs/commercial-readiness-audit.md`：商用就绪度审计。结论——单机自用可以，团队内部接近，
  **对外商业化不行**。列出 20/55 源文件零测试触达、零压测、四类商用硬门槛（默认 API 裸奔 /
  无隔离无 RBAC / 单 JSON 存储并发恢复未验 / 无自身可观测性）与 16-24 人日的补齐清单
- backlog 登记 10 条商用待办（C1-C10），其中 C1-C4 为「不修不能卖」

- SBOM 写法选型记录（`docs/sbom-choice.md`）：实测 `cyclonedx-py environment` 与
  `requirements` 在 CI 那种「只装了扫描器、没装项目依赖」的干净环境下的差别。
  结论：前者退出码 0 但产物 50 个组件全是扫描器自己的传递依赖，**NetMind 依赖一个都没有**；
  后者 12 个组件正好是声明依赖。绿但空的 SBOM 比红的更危险——采购会拿它当数

- `scripts/ci_audit.py` + 门禁 `ci-steps-are-executable`：**把 ci.yml 里每条可实跑的
  命令拿过来真跑一遍**。用 PyYAML 真解析（手写正则只认出块标量 `run: |`，
  内联的 `run: pytest -q` 全漏，那正是最该跑的）；按命令逐条过滤掉装依赖的部分
  （`npm ci && npm test` 整块当 install 会把真正该验的 `npm test` 跳过）；
  模拟 CI 的 setup-python 把 venv bin 放上 PATH。已反验：把 SBOM 换回当初的
  `-o/-t` 写法会被拦下，换成正确写法放行

### Fixed
- CI 审计初版会把 `loop-gates` 那一步也跑一遍——那是门禁执行器自身，
  在门禁里再跑它等于门禁 → 审计 → 门禁 无限递归。已显式跳过并标注原因

- 状态文件用自指字段 `head` 冒充当前 HEAD：`save()` 发生在提交**之前**，所以这个值
  永远指向「包含本状态的 commit 的上一个」——差一个是结构性的，改不掉。改名为
  `based_on`（本状态基于谁写下），并在 `_field_semantics` 里写明差异
- 新门禁 `state-based-on-is-honest`：禁止 `head` 字段回归、based_on 必须是真实
  存在的祖先、且落后 HEAD 不得超过 3 个 commit（状态快照过期了就该重跑而不是续用）

- **CI 的 SBOM 步骤一直是红的，而且即使跑通也是错的**（外部复核发现，此前我一直只说「supply-chain 已修」）：
  ① `cyclonedx-py environment --outfile x.json -o frontend -t python` 在 cyclonedx-bom 7.5.0 下退出码 2——`-o` 是 `--output-file`（要文件路径，给目录报 can't open 'frontend': Is a directory），`-t` 根本不是合法参数
  ② 更严重：supply-chain job **从不安装 backend/requirements.txt**，用 `environment` 子命令扫的是 runner 环境（pip/pip-audit/cyclonedx-bom），**不是项目依赖**。绿的 SBOM 比红的更危险——采购会拿它当数
  改为 `cyclonedx-py requirements --output-file netmind-sbom.json`（working-directory: backend），从声明文件生成，无需安装，实测 12 个组件覆盖全部声明依赖
- `loop.py` 的 `status` / `gates` 是只读命令却每次都写 state.json——查一眼状态就把已提交的快照弄脏，而脏的正是下次接手时读到的第一份文件
- `cmd_metrics` 把 `gates_total` 写到顶层而打印的是 `metrics.gates_total`，后者永远停在旧值（长期显示 15 而实际 16）
- 指标 `tests_passed` 名实不符：数的是 `def test_` 定义个数，parametrize 展开的用例没算进去（119 vs 实际 124），且「定义数」既不是用例数也不是通过数。改用 pytest --collect-only 的权威结果并更名为 `tests_collected`

### Added
- 新门禁 `sbom-covers-declared-deps`：**把 CI YAML 里写的 SBOM 命令真跑一遍**，校验产物是合法 CycloneDX 且覆盖 requirements.txt 里每个声明依赖。已反验：换回旧写法会被拦下

- 厂商能力矩阵（`diagnose/vendor_matrix.py` + `GET /api/vendors`、`/api/vendors.md`）。每家厂商带**验证等级**：verified（已在真实设备跑通采集）/ declared（映射与依赖齐备未验）/ blocked（缺插件，标出卡在哪）。README 不再自述厂商清单，只引用矩阵
- 映射表补 Cisco 系 kind（`ios`/`iosxe`/`iosv`/`cat9k`→`ios`，`nxos`/`nxos_ssh`→`nxos`，`iosxr`→`iosxr`）——此前厂商矩阵声称支持而代码里根本没有这些 kind

### Fixed
- 厂商支持一度只是 README 的一句描述加 drivers.py 的映射表，两处都可能与实态漂移（此前已漂移过一次：映射列了 nokia/srl 而依赖未声明插件）。现改为代码可导出的矩阵，并有门禁与测试锁住「矩阵与映射不得不一致」

- Linux/FRR 系设备的只读采集走 netmiko 直连（`diagnose/linux_collect.py`）。napalm 5.2 核心驱不了这类设备，而实验台拓扑正是这类型——原实现只挂了 napalm 一条路，导致诚实表的「read-only collection ✅ Real」对 Linux/FRR 从来不成立。现实测可采到真实接口状态/路由表/uptime
- 显式驱动映射（`diagnose/drivers.py`）：未知 kind 不再静默兜底成 Arista EOS
- `requirements-drivers.txt` 补可选插件 `napalm-nokia` / `napalm-srl`（此前映射表列了这两个驱动但依赖里从未声明，永远走不通）
- 真实采集结果 fixture `tests/fixtures/lab/live-collection.json`（真 SSH 端点，含正例与两个反例）

### Fixed
- **驱动映射三处错误**：① 映射到 napalm 不存在的 `'linux'`（所有 Linux/FRR 设备必然 ModuleImportError，而错误被混进 errors 看起来像「设备连不上」）② 兜底 `'else eos'` 把任何未知型号当 Arista 下命令 ③ `nokia`/`srl` 两个驱动在声明依赖下永远不可用
- 采集回来的用法/报错文本不再当作数据存储：BusyBox 的 `ip` 不认 `-br`，会把用法说明打回来，此前被原样收进结果——「看起来有数据其实是报错」的污染最难发现
- `send_command(strip=True)` 是 napalm 签名，netmiko 的 `BaseConnection` 不收（实测 TypeError）

- 真实 FRR/zebra 路由表 fixture（`frr-routing-table.txt` / `frr-routing-table-r1.txt`），补上此前缺失的路由数据维度
- 新门禁 `routing-data-is-real`：校验路由 fixture 含真实路由行、且记录了 zebra 对 `SYS_ADMIN` 的依赖
- `scripts/lab.sh measure` 增加 FRR 守护进程状态与真实路由表输出

### Fixed
- `scripts/lab.sh` 三个自埋的 bug（此前一直手工敲等价 docker 命令，脚本本身从未被完整执行过）：
  ① 缺 `--cap-add=SYS_ADMIN`，zebra 静默起不来——watchfrr 照常拉起 staticd，但 zebra 进程不出现，vtysh 只报「zebra is not running」，真因 `privs_init: cap_set_proc failed` 藏在别处
  ② 客户端循环给两个容器都分配 `192.168.1.10`
  ③ `set -euo pipefail` 碰上 ping 在 100% 丢包时的非零退出码会当场退出——而「全断」恰恰是最该测出来的场景

- 前端首次有测试：`frontend/src/lib/format.js` + 12 个用例（node 内置 runner，零依赖）。此前 `package.json` 连 test 脚本都没有，CI 只 build 不 test
- CI 的 `frontend-build` job 补上 `npm test`
- 新门禁 `frontend-has-tests`：校验 test 脚本存在、测试文件存在、**且 App.jsx 真的 import 了被测模块**（否则测的是副本不是运行的那份）
- 新门禁 `deps-pinned-and-audited`：依赖不得出现 `>=` / `^` 浮动范围

### Security
- `docker-compose.yml` 补注释说明「token 留空 = 仅本机可访问」是安全默认值，
  避免部署方误以为必须配或误配了空串
- 依赖升级消除全部已知漏洞（`pip-audit` 与 `npm audit` 均 0）：fastapi 0.115.6→0.142.2（带 starlette 0.41.3→1.7.0，原有 19 条 CVE）、python-dotenv 1.0.1→1.2.2、pytest 8.3.4→9.0.3、langgraph 浮动→1.2.12、vite 8.0.13→8.3.2（连带修掉 nanoid/postcss 高危）

### Fixed
- `validate_project.py` 的路由提取在新版 FastAPI 上抛 `AttributeError`：0.142 起 `include_router` 产出 `_IncludedRouter` 包装对象，既无 `.path` 也无 `.routes`，真实路由在 `.original_router.routes`。改为逐层下钻、兼容三种容器形态
- `compactLabel` 的空值占位符从来没显示出来：原实现先取 `'--'` 再过 `[_-]+→' '` 规则，占位符被吃成单个空格。已短路返回
- `CliRunner(mix_stderr=...)` 在 click 8.2+ 已移除，改为版本兼容写法

- 真实闭环 `diagnose/closed_loop.py`：注入 → 诊断 → 处置 → 重测 → 验证。三条不可让步的规则：没重测不许报 success、重测没改善触发回滚、探针失败如实记异常
- 闭环的实验台适配 `diagnose/lab_adapter.py`（真调 tc / ip link / ping）
- `docs/closed-loop-run-report.md`：三场景真实跑测报告，并列出**不能**支撑的主张
- `test_closed_loop.py`：7 个反例优先的回归，重点是「处置无效时必须报失败」

### Fixed
- **自愈不再恒报成功**。`HealingReport.success` 此前默认值 `True` 且无任何代码赋值；
  `telemetry.heal()` 把 `fault` 改回 normal 再采一次样就算「处置成功」——与是否真做了事无关。
  现 `success` 只能由实测前后对比推出，`verified=False` 时恒为 False
- `test_core.py::test_fault_heal` 此前断言 `heal['success']` 为真——把假象写成了测试契约，
  反过来阻止修复。已改为断言「模拟路径必须承认未验证」

- 真实网络实验台 `scripts/lab.sh`：用 docker 起两个 FRR 路由器 + 客户端，布出真两跳 L3 路径（client1 → r1 → r2 → 远端段），并可注入 netem 拥塞与断链故障
- 真实遥测采集 `diagnose/lab_collector.py`：解析真实 ICMP 报文与网卡计数器，产出 measurement 而非常量
- 真实数据 fixture `tests/fixtures/lab/`：三态抓包原文 + 网卡计数器实测带宽
- `tests/test_real_lab.py`：11 个基于真实抓取的回归

### Fixed
- **诊断置信度不再是编造的常量**（违反 CONTRIBUTING 规则 2）。此前 link_down/congestion/anomaly_traffic 分别硬编码 .98/.92/.88，与证据无关——实验台实测同样 120ms 延迟（`tests/fixtures/lab/throughput-real.json`），带宽 18.66Mbps 与 4.01Mbps 的置信度完全相同。现由证据强度、样本量、是否有独立佐证推导
- **拥塞判定不再把延迟与带宽绑死**。旧规则要求 `latency_ms > 50 and throughput_mbps < 60`，60 是绝对 Mbps 阈值，在高速链路上同条件会漏判。实验台实测（数据见 `tests/fixtures/lab/throughput-real.json`，采集方式 `scripts/lab.sh measure`）：注入 120ms 延迟不限速时带宽 18.66Mbps，与健康态 21.08Mbps 接近——延迟升高与带宽受限是独立的两件事。现改为延迟劣化即可判定，带宽仅在给出基线时作佐证，且按相对跌幅判定
- **丢包以报文计数为准**，不再采信 ping 自报百分比（10 发 9 收自报 0%，回归见 `backend/tests/test_real_lab.py`）
- `TelemetrySnapshot.source` 增加 `real`/`lab` 取值——此前 Literal 只列模拟侧，真实采集的数据在 schema 层就存不进来

- 变更提案（config-diff）：下发前把「将改什么」显式摊开，危险项排前并标注必须走审批流，输出可评审的 Markdown（`core/config_diff.py`，8 个测试）
- 无限迭代循环协议：BUILD → TEST → IMPROVE → PLAN → STATE，每轮一个可验证增量，门禁声明失败退路，状态落盘保证永远有下一步（`.netmind-loop/`）
- 去 AI 味密度门：客户可见面按密度检测空洞套话、无源数字、元评论、装饰性 emoji、过度格式化（`scripts/copy_lint.py`）
- CI 新增 `loop-gates` 与 `supply-chain` 两个 job（后者含 pip-audit / npm audit / SBOM）
- `LICENSE`（MIT 文件此前缺失，尽管 README 与 pyproject 均声明 MIT）
- `CLA.md` 草案：记录「已接受贡献不可追溯改协议」这一窗口，并给出 DCO 方向
- `CONTRIBUTING.md` 第 5 条：营销面可核查律（规则 2 从代码平移到客户可见文本）
- Dependabot 覆盖 pip / npm / github-actions 三条

### Changed
- 门禁退路体系：新增 `blocked` 状态与 `loop.py block`，避免循环停在需人工判断的待办上
- 死模块门禁由 `autofix` 降级为 `block`——移动代码需要语义判断，不满足 autofix 门槛

### Removed
- `core/sqlite_store.py`：完整但从未接线的 23 行 KV 存储。零引用属死代码；如商业化确需真实 DB 后端，另立一轮重新实现并接线（git 历史可取回）


### Security
- 危险操作门禁按语义判定：del-flows / mod-flows / iptables -F / link down / route del / addr del，与设备名无关。
- 回滚特权基于服务端签发的 cookie 登记表；未登记命令走审批门禁。
- POST `/api/deploy/{id}/rollback` 真实执行回滚计划并逐命令校验；未部署返回 409。

### Changed
- `DeployResult.rollback_complete` 区分回滚全部成功与部分尝试。
- tc 接口名严格策略仅限仿真；真实驱动接受标准接口名。
- 前端 security_passed / rollback_ready 取自实际结果。

### Removed
- `backend/build` 构建产物出库；`.gitignore` 增加 `build/`。

### Added
- `netmind audit` 只读巡检 v1 与对应回归测试（后端 67 项）。

## [0.1.0] - 2026-08-22

First public release. The closed loop is real where it claims to be, and honestly labelled where it is not.

### Added
- Intent-driven closed loop: NL intent → plan → verify → deploy → telemetry → diagnose → heal, with offline rule-engine fallback and optional OpenAI-compatible LLMs (DeepSeek / Qwen / OpenAI / Ollama presets).
- `netmind diagnose <containerlab-topology>`: structure checks (dangling endpoints, IP conflicts, isolation, invalid mgmt addresses), optional live interface collection via napalm, cached LLM root-cause analysis.
- Policy safety: semantic conflict detection (QoS guarantee × ACL deny), security allowlist/deny-keywords checker with approval workflow and unattended-policy gate, transactional rollback plans that themselves pass the security checker.
- Real device drivers behind explicit gates: netmiko execution + napalm read-only collection (`NETMIND_ENABLE_REAL_COMMANDS`), ncclient for NETCONF; everything dry-run by default.
- Optional bearer-token auth for all non-GET API requests (`NETMIND_ADMIN_TOKEN`).
- LangGraph adapter: uses real LangGraph StateGraph when installed, falls back to a built-in compatible engine.
- React dashboard (9 pages) + WebSocket events; MCP-style tool registry (24 tools) exposed as `netmind-tool-gateway/1.0`.
- Packaging: `pip install ./backend` provides the `netmind` CLI; single-sourced version.

### Changed
- Deployment results carry an explicit `mode` field (`simulated` | `dry-run` | `real`); dry-run never reports success as a real push.
- Telemetry snapshots are labelled with their source (`simulated` by default).

### Removed
- Competition-era vanity modules (feature-matrix completion scores, benchmark runner, repository status probes) and the fake mininet driver stub.

### Fixed
- Deleted configuration (models/agents/templates/workflows) no longer resurrects after restart: seeding only runs on an empty store.
- Store persistence is debounced (dirty-flag + background flusher) instead of a full JSON dump per request.
- Step durations in audit trails are measured, no longer padded with hardcoded offsets.
