# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]
### Added
- 门禁 `readonly-cannot-write-anything`：**全站枚举** OpenAPI 里每一个
  post/put/patch/delete，断言只读凭据一律返回 403。只读凭据此前只被手工试过
  几个端点，从没有全站枚举过——而「某个新加的端点忘了接只读校验」正是这个
  项目反复吃亏的形态：测试测的是被挑中的那条路径，没被挑中的那些没人知道。
  实测 70 个写方法端点全部符合，但当时**没有任何东西在保证它继续符合**。
  反例证伪有效：把 POST 加进安全方法集 → 一次枚举出 26 个「只读凭据本该拦住、
  却返回 200」的端点。同时钉住反面——管理员凭据必须仍能通过，否则一个
  「谁都拒绝」的退化实现也能让这条门禁变绿

- **MCP stdio 服务**（`netmind mcp`，backlog `B5-mcp` / Roadmap Phase 3）。
  此前只有 `MCPProtocol` 那个进程内 HTTP 适配器（`/api/mcp/*`），并不是真正的
  MCP 服务——外部客户端按 MCP 协议连不上，README 当时如实写的是
  「MCP-**style** tool registry」与「Phase 3 未开始」，所以这不是坏承诺，
  是待交付的功能。现支持 `initialize` / `tools/list` / `tools/call` / `ping`
  与 `notifications/initialized`（notification 不回响应，符合 JSON-RPC 规范）。
  协议层 `handle()` 是**纯函数**、IO 循环单独一层，否则测协议每次都要起子进程。
  补 18 个用例：五类标准错误码、notification 无响应、坏 JSON 仍回合规响应。
  两条不妥协并已反例证伪：`tools/call` **默认干跑**（stdio 不构成放宽执行的理由）、
  `tools/list` **只列已启用工具**（清单给了就会有人照着调）

- CLI 补三个命令，覆盖此前只在 HTTP 层存在、CLI 摸不到的端点：
  `netmind vendors`（厂商能力矩阵，**验证等级逐行标出**：verified 是真机跑通过的、
  declared 是映射齐备未验、blocked 是缺插件）、`netmind readiness`（配置齐全度与
  真实计数）、`netmind notifications`（告警与关键事件，空结果会说明）。
  补 6 个用例，并在写门禁时发现第一版把厂商字段写成 `verification`（真实字段是
  `level`），于是「验证等级」整列显示 `-`——而那一列正是这张表唯一要说的事。
  **一列全是 `-` 的表比没有这张表更糟**：看起来像「没有等级信息」，实际是「没读对字段」

- `frontend/src/lib/charts.js`：折线取点与列表关键词检索。Sparkline 此前
  `Number(x[field] || 0)`——测不到的字段被当成 0，于是延迟图上会画出一条真实的
  「0ms」读数（比缺测更坏，它看起来像个好消息）；遥测字段改成可缺之后这条路更是
  直接被打开。另外 `Number('abc')` 是 NaN，NaN 进 `points` 属性会让整条 polyline
  不渲染——**一个坏行毁掉整张图**，而 SVG 不报错、只是空着。
  现取不到值就**不画那个点**、坐标夹进留白带、丢点数回报出来；关键词检索在两个
  页面各写了一份，现统一。前端 78 → **92**
- `frontend/src/lib/graph.js`：工作流图的「结构与可编辑文本」互转。解析时把
  不合法的行**收集进 `problems` 返回**，不再 `.filter(e => e.length === 2)`
  悄悄吞掉——用户打 `a -> b -> c` 此前那条边直接消失且无任何提示。箭头写反的
  （`b <- a`）自动纠正并告知；指向不存在节点的边会被点名
- `frontend/src/lib/topology.js`：拓扑布局与连线端点解析。修两处静默出错：
  ① 同名节点原先 `acc[id] = ...` 互相覆盖，等于凭空少一台设备，现错开摆放并回报；
  ② 连线端点找不到时原先 `|| [10, 10]` 回退到固定坐标——**画出来的拓扑在撒谎**，
  现改为跳过并在 `<title>` 里写明缺哪个端点
- 门禁 `frontend-request-layer-is-tested` 增补**调用点与声明的参数个数比对**。
  抽模块时改了签名、调用点没跟着改，这类漂移实测咬了三次，而 `npm run build`
  与模块自身测试**都是绿的**（它们都不碰调用点），只在浏览器里炸。
  参数切分做了括号深度感知——`summaryCell(v, { yes, no } = {})` 里花括号内也有逗号，
  朴素 split 会误报，**出误报的门禁比没有门禁更糟**。已用「改回旧签名」反例证伪
- `frontend/src/lib/client.js`：请求层（`request` / `useApi` / `normalizeList` /
  `toastMessage` / `copyText` / `downloadText`）从 App.jsx 抽出。抽它的理由不是
  「文件太长」——App.jsx 里还堆着十来个页面组件，那是另一回事——而是**这段此前
  一行测试都写不了**：`node --test` 只能直接 import 纯模块，而 App.jsx 是带 JSX
  的入口文件。而 `request()` 承载的认证契约已被打错过两次
- `frontend/src/lib/constants.js`：主题预设、字体、状态文案、示例意图、模型预设
  等静态数据同样抽出（零逻辑零 JSX）。App.jsx 1887 → 1676 行
- 9 个新用例覆盖请求层：Bearer 头、不自造 `X-NetMind-Admin`、无默认凭据、
  只读/管理员凭据切换、`credentialKind` 不漏进 fetch、body 自动 JSON 化、
  401 与 403 的可区分报错、normalizeList 的各返回形状。前端 46 → **55**
- 门禁 `frontend-request-layer-is-tested`：要求请求层留在 `lib/` 且有测试、
  `lib/` 下不得出现 JSX（否则又 import 不了），并明确要求钉住那两次打错的行为。
  两个反例均已证伪：把 `request()` 长回 App.jsx → 抓到；往 lib 里塞 JSX → 抓到
- 门禁 `changelog-sections-not-duplicated`：Unreleased 段曾堆到 **13 个小节**
  （每轮提交各自追加一个 `### Fixed`），手工合并过一次但没加门禁，几个回合就退回
  原样。**只修一次的东西等于没修。** 现合并为 4 个小节并由门禁锁住
- 门禁 `no-inert-credential-surface`
- `scripts/verify_linkdown.py`：在真实设备上验 `link_down` 处置路径，两个场景都取
  **设备侧独立证据**（读路由表 + 设备自己 ping），不采信 NetMind 自报。
  场景 A 备份路由指向真实网关 → 丢包 1.0→0.0、延迟 999.0→0.209ms，设备路由表出现
  该条、设备侧 `0% packet loss`；场景 B 指向黑洞网关 → 未改善（丢包 0.0→1.0，
  比处置前更糟）→ 触发回滚 → 设备路由表确认该条已撤下、`success=False`。
  诚实表里「link_down 路径未在设备实跑」那条 ⚠️ 据此收口
- 门禁 `fixtures-are-self-consistent`：真实抓包必须**自证**。ping 文件自报的
  transmitted/received 与 round-trip min/avg/max 要与它自己的报文行对得上，
  seq 连续，断链态不得有 round-trip 行；`key_finding` 引用的每个实测值要在真实
  数据集里查得到。已用两种编法验证有牙齿：统计行照抄真数据只把回包 time 随手编
  （被抓出 min/max/avg 三项全不符）、RTT 自洽只把收包数从 10 改成 12（被抓出
  自报 12 个回包但只有 10 行）——两种编法看起来都很真，两种都被抓住
- 前端展示层的取值决策抽到 `frontend/src/lib/display.js`（`frontend/src/lib/auth.js`
  同轮新增）：指标取值、健康分、健康环、验证摘要、置信度——都是「用户被告知什么」
  的决策点，此前散在 `App.jsx` 里一行测试都没有。补 20 个用例，前端 12→30
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

### Changed
- **诚实表的 ⚠️ 现在只表示「今天的限制」**。此前 9 条 ⚠️ 里有 3 条讲的是**已经
  修好的坑**（缺测哨兵值、诊断置信度默认 0.9、状态端点恒为真），正文以
  「⚠️ previously …」的形式留在限制列里。留着是**反向误导**——读表的人据此
  判断能不能用，而留着会让他们以为问题还在。现移到表下方一张「修过的同类问题」
  小表（症状 → 现在），⚠️ 收敛为 7 条：环境限制 1、刻意的设计选择 4、
  结构性限制 1、真实取舍 1。门禁 `honesty-table-signals-current-state` 锁死，
  并要求「修过的同类问题」小节必须存在——否则把历史移出 ⚠️ 就等于丢信息
- **写明部署模型：一台实例 = 一台设备**（`docs/DEPLOY.md` 第 7 节 + 诚实表）。
  由此澄清一个此前措辞有误导的缺口声明——原文写「no per-endpoint or per-device
  scoping — an admin may act on every device」，暗示存在设备群；实际上单实例只连
  `NETMIND_SSH_HOST` 那一台，**「按设备」这根轴根本不存在**。
  C7 据此按「错框架」关闭而非「没做」：两档凭据已交付，
  按端点细分在单人/小团队自托管单设备场景下是假想需求。
  要做设备群纳管是另一个产品（牵动凭据模型、每次执行的目标选择、按设备授权）
- 门禁 `no-inert-credential-surface`：要求凭据接口自述不可用于连接，并探测
  `STORE.credentials` 是否出现消费方——真出现了就要求重新评估本门禁与诚实表措辞，
  不让两处说法漂移。两种反例均已注入验证
- **面板改为生产托管**。此前 `frontend` 容器跑的是 `npm run dev`（Vite dev
  server）——把开发服务器当产品发出去，谈不上「可直接商用」：HMR 端点暴露、
  源码不压缩、构建产物根本不进镜像。现改为多阶段构建 → nginx 托管 `dist/`
  （镜像 74MB，源码与 node_modules 不进最终镜像），带内容指纹的资源长缓存
  `immutable`、`index.html` `no-store`，并配了容器级 `/healthz`
- **API 基址改为启动时注入，默认同源**。`VITE_*` 是构建期变量，所以镜像里烤死了
  `VITE_API_URL=http://localhost:8000`——同一份镜像换访问地址就指错地方，
  而且跨源发 `Authorization` 头会触发 CORS 预检，预检失败的表现常常像网络问题。
  现在 nginx 在启动时替换 `index.html` 里的注入点，默认空串 = 同源，
  由 nginx 把 `/api` 与 `/ws` 反代到后端
- compose 补 healthcheck，frontend 用 `condition: service_healthy` 等后端真的就绪
- `vite.config.js` 配了同样的 `/api`、`/ws` 代理，开发与生产的请求形状一致
- 门禁退路体系：新增 `blocked` 状态与 `loop.py block`
- 死模块门禁由 `autofix` 降级为 `block`——移动代码需要语义判断
- `DeployResult.rollback_complete` 区分回滚全部成功与部分尝试
- tc 接口名严格策略仅限仿真；真实驱动接受标准接口名
- 厂商支持一律以 `GET /api/vendors` 矩阵为准，README 不再自述
- 移除死依赖 `recharts@3.8.1`（声明了但 `src/` 从未 import，白装白交付还扩大
  供应链面）；`vite` 从运行时依赖移入 devDependencies

### Removed
- **`anomaly_traffic` 的自动处置（`tc qdisc add ... netem rate`）——方向是反的**。
  该诊断唯一的触发条件是「带宽相对基线跌幅 ≥50%」，而处置是限速，也就是
  「带宽掉了 → 把带宽再限死一点」。拿实测数据推演（健康态 21.08Mbps、
  限速态 4.01Mbps 判 anomaly_traffic）：限到 5Mbps 的限值**高于**已跌下去的
  4.01Mbps，基本是空动作；链路跌到 8Mbps 时则是把它弄得更糟。根因是这个
  分支原本要检测「流量过高」，但代码里根本没有带宽过高的判定，只有「带宽跌
  太多」一条，名字与触发条件对不上。带宽下降是症状不是病因，没有哪一条能靠
  限速修好。**诊断保留**（它标记了真实异常），`heal()` 改为明确拒绝并说明
  原因。设备侧读回确认拒绝后 `qdisc noqueue`、路由表未变——什么都没下发。
  门禁 `remediation-matches-diagnosis-direction` 锁死
- `core/sqlite_store.py`：完整但从未接线的 23 行 KV 存储。零引用属死代码
- `backend/build` 构建产物出库

### Fixed
- **`dependabot-present` 只断言「文件存在」——删掉 npm 那一整块它照样 PASS**。
  它宣称的是「依赖自动更新已启用」，而删掉 npm 块之后前端依赖从此没有任何
  CVE 响应。现按**本项目实际用到的生态**（pip / npm，对应
  `backend/requirements.txt` 与 `frontend/package.json`）逐个核对，并确认每条
  配置的 `directory` **在仓库里真实存在**——写错目录的 dependabot 配置不会
  报错、也不会更新，同样是装饰。两条反例都验证会红（删 npm 块 / 目录名写错）

- **`ci-security-gates` 只是文本包含判断——把 CI 里两个扫描步骤整段删掉，它照样 PASS**。
  原实现只查 `'pip-audit' in ci`。这意味着 `ci.yml` 里写一行
  `# TODO: 加 pip-audit` 就能让「依赖漏洞扫描已就位」这条安全声明变绿，
  而 CI 实际上**一次漏洞都没扫**。现改为行为判定：解析 YAML，要求存在一个
  **真的会执行、且失败会让 job 变红**的扫描步骤——命令不能只出现在注释或
  step 名里，不能被 `|| true` / `; exit 0` 吞掉，步骤不能挂
  `continue-on-error: true`。三条反例都验证会红：整段删除 / 两个扫描都被吞掉
  （报错会点名是哪两个）。反向也钉住：只要**有一个**真扫描就通过，与该门禁
  「pip-audit 或 npm audit」的原始契约一致——不把契约偷偷改成两个都必须有

  本轮又一次**无效证伪**，同样记下来：第一次注入只把 `- name:` 注释掉，结果
  下面的 `run:` 挂到了上一个 `setup-node` 步骤上，**扫描其实还在跑**，门禁当然
  绿。改成整块删除步骤才真正验到底。**注入本身无效时，PASS 说明不了任何事**——
  这已经是本项目连续第三次因为「注入没生效」而差点误判防线

- **门禁审计第五轮：又抓到三条「看似严实则松」的假防线、两处文档缺陷，外加一个
  反复咬人的幽灵**。判据始终是同一条：**注入反例后门禁会不会红**。

  1. `vendor-matrix-is-authoritative` —— 把 `cisco-ios` 从 `declared` 谎报成
     `verified`（声称真机验过、实际从没验过）时照样 PASS。原实现只查了「至少
     有一个 verified」和「fixture 采到东西」，没查**每一个** verified 是否有
     自己的证据。现按 `transport/driver` 组合逐个厂商核对采集 fixture，且**只
     认 `collected` 不认 `errors`**：fixture 里 r1 那条 napalm/eos 是真去连了但
     被拒（Connection refused），那是「试过」不是「验过」，拿它当证据就是撒谎。
     两条反例都验证过会红（谎报 cisco-ios / 谎报 juniper-junos）

  2. `security-doc-matches-behavior` —— 文档清单是**手写**的：修 SECURITY.md 时
     顺手添了 `docs/*.md`，`CONTRIBUTING.md`、`CLA.md`、`.netmind-loop/protocol.md`
     就各漏一份。实测往 `CONTRIBUTING.md` 塞回那句错话，门禁照样绿。现从
     `git ls-files` 推（`--cached --others --exclude-standard`，把**新增但还没
     提交**的文档也算进来——那恰恰是最该拦住的时刻）；非 git 环境退回按目录扫，
     任何一条路径都断言「确实扫到了东西」，不让扫描范围静默退化成零

  3. `no-missing-as-zero` —— 只扫 `App.jsx`，而渲染逻辑早就抽进 `frontend/src/lib/`
     了（display / charts / graph / topology）。实测往 `lib/charts.js` 放一个
     `m.latency_ms || 0`，照样 PASS。与第 2 条是同一个错：**代码搬了家，
     手写清单没跟着搬**。现扫整个 `frontend/src`，并剥掉块注释——charts.js 与
     display.js 的注释里**引用了这个坑本身**当反例，不剥会被判成违规

  4. `no-ai-smell`（`scripts/copy_lint.py`）—— 覆盖面从 7 份手写清单扩到
     **13 份**（`CLA.md` / `CONTRIBUTING.md` / `docs/commercial-readiness-audit.md` /
     `docs/load-test-baseline.md` / `docs/sbom-choice.md` / `.netmind-loop/protocol.md`
     此前全不在其中），口径与第 2 条共用 `scripts/docs_scope.py`。扩面当场抓出
     **12 处**无源数字，5 处是真问题（已给出处：`store.py` 的常量名、复现脚本、
     交叉引用），其余是判定过严的误报
     ——「门禁一旦开始误报，人就会开始忽略它，那比漏检更糟」

  5. 诚实表 `Credential tiers` 一格里，**两版改写被拼在一起而不是替换**——同一
     段「✅ Two — `NETMIND_ADMIN_TOKEN` (all methods) and ...」出现了两次，前半
     句已被后半句作废却还留着。读者只能靠猜才知道哪半句是现状，**而诚实表不许
     靠猜**。已合并，并给 `honesty-table-signals-current-state` 补了「同格不得
     出现重复长片段（40 字符）」的检查——短于 40 的是常见措辞，长于它的重复
     几乎只可能来自复制粘贴事故

  第 2/3/4 条是**同一个错**：代码或文档搬了家，手写清单没跟着搬。所以口径收成一处
  （`scripts/docs_scope.py`，从 `git ls-files` 推，含新增未提交文档），
  谁需要谁 import，不许再抄第二遍

  另修一个**不是门禁缺陷、但一直在污染门禁结论**的幽灵：`__pycache__` 里的陈旧
  字节码。此前多次出现「明明 `git checkout` 还原了，门禁还报一模一样的错」，
  看着像真缺陷，其实是 Python 加载了注入实验期间写下的 `.pyc`。根因是门禁
  反复做「注入 → 跑 → 还原」，而它自己在还原之前就把注入态缓存了。
  现 `gates.py` 与 `loop.py` 开头都设 `sys.dont_write_bytecode` 并把
  `PYTHONDONTWRITEBYTECODE=1` 传给子进程（pytest 等），**不写就没有幽灵可留**。
  已按原场景复验：注入 → 变红 → 还原 → 变绿，全程不手动清任何缓存，
  产出的 `.pyc` 数量为 0

  本轮还踩了两次**无效证伪**，都记下来：

  · 第一次往 `CONTRIBUTING.md` 注入时写的是 `NETMIND_ADMIN_TOKEN`，而门禁只
    匹配小写 `token` 与首字母大写 `Token`，全大写 `TOKEN` 匹配不上——门禁绿是
    **我的注入没生效**，不是防线失效。顺带把这条洞补了（token 一词不分大小写）
  · 给「可复算文档」加豁免时，第一版做成**整份文件豁免**，结果 13 份文档里
    9 份（含 README）直接免疫数字检查。那不是修门禁，是给营销话术开后门。
    收到「只有表格行豁免，散文一条不放过」

  补这条豁免时又撞见一个**更老的洞**：数字的出处只看「上一行/下一行有没有
  反引号」，于是**只要上一行带 `代码`，整行无源数字就被放行**——实测在 README
  末尾追加一句「吞吐提升 3 倍，覆盖率 87%」，门禁放行。原因是我先写了个更松的
  判定（找最近的非空行）才撞见的。证据判定现分三档：同一行 / 紧邻的同段行 /
  隔一个空行的 `>` 注释块；跨段落撞上普通散文**不算**注解

- **门禁审计第四轮：`healing-is-guarded` 在「缺处置原语时编一条命令」时照样 PASS**。
  该门禁检查了「没配处置接口要拒绝」，却没检查「这个诊断压根没有处置原语时
  也不能编一个」。而 `anomaly_traffic`（方向反）与 `config_error`（缺归属证明）
  正是被刻意移出处置表的两个诊断——真把它们加回去，门禁看不见。
  已补：`build()` 对这两类必须抛 `RemediationUnavailable`。
  反例证伪时也踩了一次**无效证伪**：第一次注入写在 `spec = REMEDIATIONS.get(kind)`
  **之前**，下一行立刻覆盖回 `None`，注入根本没生效而门禁当然照过——
  **注入本身无效时，PASS 说明不了任何事**

- **门禁审计第三轮：风险最高的三条「数据是真的」类门禁，逐条注入验证——全部是实的**。
  这几条声称的是最贵的性质，所以先审它们：

  | 门禁 | 注入的回归 | 结果 |
  |---|---|---|
  | `collection-not-guessed` | 兜底分支改回 `eos`（未知型号当 Arista 下命令） | ✓ 抓到 |
  | `routing-data-is-real` | 删掉路由 fixture 里所有真实路由行 | ✓ 抓到 |
  | `data-durability-drill` | `restore_from` 空转却报「已恢复」 | ✓ 抓到 |
  | `data-durability-drill` | `save()` 改成非原子直接覆写 | ✓ 抓到 |

  第二轮那三条「看似严实则松」（只查静态证据、不碰消费它的代码）在这几条上
  没有重演——说明失灵的是**具体那几条**，不是整个门禁体系。

  过程中有一次 `data-durability-drill` 在干净代码上失败，查下来是**上一轮的
  注入残留没还原干净**（用 `cp` 从临时备份还原，备份本身已被污染）。
  是门禁把它抓出来的——这正好是它该做的事。

- **门禁审计第二轮：审过的门禁里又抓到三条，另确认六条是实的**。
  做法不变——给门禁注入它声称要防的那个回归，看会不会红。

  | 门禁 | 注入的回归 | 结果 |
  |---|---|---|
  | `no-dead-local` | 函数体加一个从未使用的局部变量 | ✓ 抓到 |
  | `no-dead-module` | 造一个零引用模块 | ✓ 抓到 |
  | `deps-pinned-and-audited` | 把 `reportlab==5.0.1` 改成 `>=` | ✓ 抓到 |
  | `system-status-is-measured` | `healthy` 恒真 / `driver` 忽略配置 / `model_online` 恒真 | ✓ 三条全抓到 |
  | `frontend-is-production-served` | 镜像改回 `npm run dev` | ✓ 抓到 |
  | `telemetry-not-guessed` | 没探针点时谎报 `source='real'` | ✓ 抓到 |

  第一轮抓到的三条（`no-fake-healing` / `real-data-not-faked` /
  `container-deploy-needs-token`）已加固；这两轮合计说明**门禁的断言数量
  与它的防护能力无关**——`no-fake-healing` 有 9 条断言、却对「恒报成功」
  这个它名字里最核心的性质完全失灵。判据只有一条：注入后会不会红。

- **门禁审计：三条核心门禁「看似严实则松」**。做法是给每条门禁注入它声称要防的
  那个回归，看抓不抓得到——不是再去找新缺陷。抓到三条：

  ① `no-fake-healing` 在 `heal()` 被改成恒报成功时**照样 PASS**。它只查静态
     fixture 里**过去某次**记下的 `success: false` 和 schema 默认值，代码现在
     是什么样它一无所知。名字声称「自愈不得恒报成功」，实际只证明
     「历史上记录过一次失败」。**fixture 证明「验过」，不证明「现在还对」。**
     已补：真跑一遍「设备拒绝执行」的路径，看当前代码给不给 False
  ② 更严重：把 `to_snapshot` 里的 `source=source` 改成 `source='simulated'`
     （**把真实采集谎报成模拟**），`real-data-not-faked`、
     `no-sentinel-measurements`、`telemetry-not-guessed`、
     `fixtures-are-self-consistent` **四条全部照样 PASS**，只有测试套件抓到。
     也就是说「真实数据不是编的」这个**项目的核心主张**，在门禁层面完全没人在管。
     已补实测
  ③ `container-deploy-needs-token` 的 `find('NETMIND_ADMIN_TOKEN')` 取的是这个字符串
     的**第一次出现**，而它在上面的注释里也出现过——锚点落在注释中段，删掉整段说明
     注释门禁照样过。已锚到变量声明行，并把上下文窗口收到贴着变量声明的尺度

  ② 那一轮还暴露一个真实缺口：compose 的注释详细解释了陷阱（网关 IP、不是
  loopback、一律 403），但**从头到尾没说「必须」**——解释了问题却没说该做什么。
  与其放宽门禁，不如把祈使句补回去

- **只读身份的前端只拦住了 1/41 个写操作**。诚实表声称「面板提前告知，而不是让
  只读用户点进去撞 403」——横幅确实弹了，但全站 41 个写操作里只有「触发自愈」
  一个有按钮级守卫，其余 40 个照点不误、照样吃服务端 403。**承诺没兑现。**
  修法不是在 40 处各加一遍守卫（41 处一定会漏，新增操作时同样会漏），而是把
  闸门放进 `client.request()`：「只读身份不许写」是**一条规则**，不是某个按钮的
  属性。覆盖率 1/41 → 41/41，将来新增写操作自动被覆盖。
  补 5 个用例 + 门禁 `readonly-ui-blocks-every-write`（三类反例均已证伪）
- **只读身份的前端只拦住了 1/41 个写操作**。诚实表声称「面板提前告知，而不是让
  只读用户点进去撞 403」——横幅确实弹了，但全站 41 个写操作里只有「触发自愈」
  一个有按钮级守卫，其余 40 个照点不误、照样吃服务端 403。**承诺没兑现。**
  修法不是在 40 处各加一遍守卫（41 处一定会漏，新增操作时同样会漏），而是把
  闸门放进 `client.request()`：「只读身份不许写」是**一条规则**，不是某个按钮的
  属性。覆盖率 1/41 → 41/41，将来新增写操作自动被覆盖。
  补 5 个用例 + 门禁 `readonly-ui-blocks-every-write`（三类反例均已证伪：
  从 request() 拿掉闸门 / 闸门条件永假 / WRITE_METHODS 清空）

- **`applyAuthMode` 与 React 的 `setAuthMode` 撞名**，本地 state setter 把导入
  遮蔽了，client 模块根本拿不到 authMode——闸门看着接上了，实际从不生效。
  改名 `applyAuthMode` 后才真的通
- **`diagnose --live` 对任何非 22 端口的设备完全不可用**。`_collect_live` 有
  `ssh_port: int = 22` 形参，而 `diagnose()` **从不传它**——无论
  `NETMIND_SSH_PORT` 设成什么，采集都打 22 端口。实测：把实验台设备映射到
  2222，采集前一律 `[]`（全部 TCP 超时），修后采到 `['r2']`（真机接口状态）。
  **设了环境变量却不被使用，是最坑的形态**：使用者只会以为自己配错了
- **`diagnose --live` 把「请求了但失败」写成「没请求」**。采集全失败时 findings
  一律是 "no device access requested"，而实况是访问请求过了、失败了。
  使用者会去查参数而不会去查连接。逐节点的失败原因（超时/认证失败/驱动不可用）
  此前也被丢掉，只留一句笼统的 notes。现两者都保留，并区分
  「没请求」与「请求了但没采到」两种措辞。补 4 个用例 + 门禁
  `diagnose-live-actually-tries`（两个反例均已证伪）

- **安全审计在从未真正检查过的设备上报告「通过」**。巡检项是 **OpenWrt 专用**的
  （`uci` / `ubus` / `dropbear`），却对着任何设备跑。实测一台 Alpine 容器：
  这些命令全都不存在，shell 回一行 `-bash: uci: command not found`，而解析器把
  **这行错误文本当成了设置值**——`PasswordAuth` 不在 {on,1} 里，于是判成 ok。
  结果：六项里四项报「通过」，而这四项**从未被检查过**；同时防火墙那项因为同样
  的原因误报了一个「发现风险项」。**这是安全工具最危险的失败模式**：使用者据此
  以为设备是安全的。现两层修法：① 读不到（空/command not found/exec-error）时
  任何解析都不可信 → 报 `unknown` 并把真实失败原因写进证据；
  ② 有任何一项没检查，结论就不能是「基线通过」——新增
  「巡检未完成（部分项目无法检查）」这个结论档。同一台 Alpine 设备修后：
  4 项 unknown、1 项 info、仅「管理面监听端口」是真的查了（Alpine 有 `ss`）仍 ok。
  补 11 个用例 + 门禁 `audit-unchecked-is-not-passed`（反例：把 unknown 改回 ok
  → 抓到）。顺带更新既有测试：summary 现在还统计 unknown/error/info，
  「读不到」与「都查了」在汇总里必须长得不一样

- **`rich.html` 把每个空行渲染成一个空的 `<h2></h2>`**。第一版是一行三元表达式
  `… if line and not line.startswith('#') else '<h2>…</h2>'`——空行也落进 else
  分支，于是 markdown 每节之间的空行各变成一个空标题，**看起来像报告缺内容**。
  同时 `#` 与 `##` 全被拍平成 `<h2>`，标题层级丢失。现按行首 `#` 个数决定级别、
  空行跳过，并补 `lang="zh-CN"`。补 4 个用例 + 门禁
  `rich-html-has-no-empty-headings`（两个反例均已证伪：空行不再跳过 → 抓到；
  层级拍平 → 抓到）

- **干跑报告从「## 3.」直接跳到「## 6.」**。第 2–5 节是条件渲染而编号写死 1–6，
  于是不下发、不自愈时报告少了第 4、5 节——读者看到编号空档，**分不清是这步
  没做还是报告丢了内容**，而合规场景里两者都会被读成「出问题了」。
  现六节恒在，没做的**明说为什么没做**（未下发到设备 / 未触发自愈 / 未产出策略集 /
  未做校验）。补 3 个用例 + 门禁 `report-keeps-every-section`（反例：把 4/5 改回
  条件渲染 → 抓到 2 条失败）

- **PDF 导出会静默丢掉全部汉字，且不报错**。两条 PDF 路径（`report_pdf` 与
  `REPORT_RENDERER.pdf_bytes`）各自手写了一份最小 PDF，用
  `encode('latin-1', 'ignore')` 编码；而报告正文是中文，base-14 的 Helvetica
  只能表示 Latin-1，于是**每一个汉字都被扔掉**。用 `pdftotext` 读生成的文件
  拿到的是 `# NetMind exec-…- Status.success## 1.  - video_meeting`，
  而 markdown 原文是 `## 1. 意图摘要 / - 描述：给会议网提高优先级`。
  **用户导出 PDF 得到一份几乎没有内容的文档，没有任何报错。**
  同一份手写实现还有两个问题：xref 表是假的（`startxref 0` 指向文件开头，
  严格校验器会拒绝）、`/Length` 是猜的。
  现改用 reportlab 生成真 PDF（依赖 `reportlab==5.0.1`），并解决字体问题：
  从系统发现 CJK 字体并逐个试到能被 reportlab 注册为止（Noto CJK 的 .ttc
  是 CFF 轮廓、reportlab 装不上，所以必须逐个试而不是取第一个存在的）。
  **找不到字体时明确报 422 并给出修法，绝不退回那份被阉割的输出。**
  实测：PDF 从 1133 字节 → 34307 字节（含内嵌字体），
  `pdftotext` 读出完整中文。补 12 个用例 + 门禁
  `pdf-export-does-not-drop-chinese`（两个反例均已注入证伪）
- **`netmind logs` 在没有日志时退出 0、stdout 全空**。循环体一次都不执行，
  使用者无法区分「命令失败了」与「确实没有日志」——CLI 是对用户说话的那一层，
  沉默在那一层最贵。现在空结果明确说明（含 limit 与查询词）
- CLI 打印日志行时用 `row['x']` 硬取字段：持久化的旧记录若缺某个字段，
  KeyError 会让整条命令崩掉，而用户看到的是「命令坏了」而不是「这条记录旧」。
  改为 `format_log_line()` 纯函数 + 缺字段兜底，来源缺失写「来源未标注」
  （与前端 `display.js` 同一套口径，不在两处各编一次来源）
- 门禁 `cli-never-silent`：空结果必须说一声、遍历型命令要有空态分支、
  不得硬取字段、CLI 与前端的「来源缺失」措辞必须一致。两个反例均已注入证伪

- 折线坐标的第一版把值域映射错了一个 band，y 算出 158 越出视口；clamp 区间也
  设成 `[floor, height]`，把 12.4 与 11.8 两个不同的值压成同一个 y，图看起来
  「没变化」——**clamp 是越界的安全网，不该毁掉带子内的有效数据**。两条都是补
  测试时抓到的，现值域映射到 [14, 86] 带内、clamp 只兜真正越界
- `filterByKeyword(rows)(keyword)` 的柯里化写法让调用点参数个数与声明对不上，
  arity 检查只能靠特例放行——而「靠特例放行」正是检查失效的开始。改成直白两参
- **`tests-are-reproducible` 门禁两次都在仓库根跑，漏掉了「换个 cwd 就挂」的测试**。
  CI 的 pytest 步骤是 `working-directory: backend` + `pytest -q`，而我本地从根
  目录跑 `pytest backend/tests`——**两个不是一回事**。本轮就有一个新测试用了
  相对路径 `backend/app/routers/system.py`，从根过、从 `backend/` 挂，
  由 `ci-steps-are-executable` 抓出来。门禁现已加第三次运行，按 CI 的方式执行；
  已在「只在根目录通过」的反例上验证会失败
- 我自己写的那条测试已改为相对**本文件**定位路径。**只在某个 cwd 下通过的测试
  不是可复现的测试**

- **「没测到」被变成「测到 999ms、丢包 100%」**。`to_snapshot` 对缺失的
  rtt/loss 填 `999.0` / `1.0` 这两个哨兵值，于是「ping 丢包到算不出 RTT」会
  变成一份「延迟 999ms、丢包 100%」的快照，`diagnose()` 据此判 `link_down`——
  可能对一台**其实正常**的设备下发处置。带宽同理：没测就填 `0.0` 也是编一个数。
  现 `TelemetrySnapshot` 的三个测量字段改为可缺，缺就是 `None`；`diagnose()`
  的 `float(x or 0.0)` 一并改掉（那会把「没测到」变成「延迟 0、丢包 0」，
  也就是一份看起来完美健康的快照）。实测：80% 丢包 + RTT 缺失现在按丢包判
  `congestion` 而非 `link_down`；两项都缺时返回 `normal` 置信度 **0.0** 并说明原因
- **告警文案声称「SLA threshold exceeded」**。项目里没有用户约定的 SLA——
  面板已如实声明「未定义 SLO 目标」——`alert` 置位的真实原因是跨过**内置**判据。
  改为直接给出实测值与被跨过的内置阈值（延迟 50ms / 丢包 5%）。门禁
  `no-sentinel-measurements` 锁死两类问题，两个反例均已注入证伪

- **UI 对「没数据」编出关于设备与数据可信度的断言，四处**：
  ① `node.ip || node.status || '可用'` —— 既没有 IP 也没有状态的设备被标成
     「**可用**」，而没有任何数据这么说
  ② `row.source || 'system'` —— 遥测来源未标注却被说成来自 system，
     直接抵消后端那套 `source=real|simulated|lab` 的来源标注
  ③ `row.ts ? … : '刚刚'` —— 没有时间戳的记录被说成「刚刚」
  ④ `health?.alerts ? … : '正常'` —— **任何检查都还没跑过**时（`health` 初始
     为 `null`），侧栏就显示绿色对勾 +「全网正常」。这可能是整块界面上最要紧的
     一句谎报；紧挨着的模型那行本来就是三态，这里补齐成一致，未知态改用中性色
  四处现由 `lib/display.js` 的 `deviceStateLabel` / `provenanceLabel` /
  `timeLabel` / `netStatusLabel` 出值，补 10 个用例，前端 68 → **78**。
  门禁与测试分层守：编造落在 `App.jsx` 由 `frontend-request-layer-is-tested`
  抓，挪进 `lib/display.js` 由 `display.labels.test.js` 抓（实测两条失败）。
  单靠门禁不够、单靠测试也不够，两边各管一段
- `timeLabel(row, locale)` 声明成两个必填、实际只传一个——行为没错但**声明在
  骗人**。改为可选参数

- **压测门禁 `load-test-no-loss` 偶发失败（实测 5 次里约 1 次）**。症状是
  「残留临时文件: 1」，而数据文件完好。查下来是**断言与写入竞争**，不是真泄漏：
  `save()` 只在构建 payload 时持锁，`mkstemp → write → fsync → replace` 这段在
  锁外，后台自动保存线程又每 2 秒跑一次，压测收尾直接扫目录就会撞上这个窗口。
  给 store 加在途保存计数与 `settle(timeout)`，压测改为**先等静默再查残留**——
  断言本身没放宽，静默之后仍有残留才算真漏。修复后连跑 8 次全过、0 残留
- **抽出过程中连续三次踩到同一个坑**并已全部修掉：① `request()` 里 `apiUrl`
  误写成 `apiPath`，build 绿灯通过而运行必崩 ② 渲染端用
  `node.id || node.name || \`node-${index}\`` 查坐标，而布局对无 id 节点存的是
  序号的**字符串**，两边 key 拼法不一致 → `const [x, y] = undefined` 白屏
  ③ 改成「主键查不到再退化到冲突键」仍不对——主键从不缺失（它就是前一个同名
  节点的槽位），两台设备照样重叠。**根因都是「让调用方自己算 key」**，
  现在布局直接按索引给出 `coords`，key 拼法只剩一处
- **抽出过程中当场发现：`request()` 里的 `apiUrl` 误写成 `apiPath`（旧别名），
  而 `npm run build` 绿灯通过**。打包器不检查函数体内的未定义标识符，这个错误在
  浏览器里是「首次 API 调用即崩」。测试一次抓到 8 条失败。
  **这说明前端此前「构建通过 = 没问题」是错的**——已作为证据写进诚实表

- **`/api/config/credentials` 是个空转接口，而字段名让人以为它能连设备**。
  条目带 `host` / `port` / `username` / `secret_ref`，读起来就是「凭这条去连设备」，
  但**没有任何代码消费它们**——驱动只读 `NETMIND_SSH_HOST` 等环境变量。
  运维 POST 一条生产设备的凭据、看到它被存下来、理所当然以为 NetMind 会用它。
  安全相关的接口上静默空转是有害的。现在每行都带 `used_for_connection: false`
  与指向真实环境变量的说明
- **`scripts/verify_heal.py` 依赖「探测目标恰好可达」这个环境残留**。注入 netem
  只能让**可达**的目标变慢；目标本来就 100% 丢包时，加不加整形都一样，诊断会判成
  link_down，验证作废（实测在实验台重建后即如此）。新增
  `NETMIND_VERIFY_BASELINE_ROUTE` 让脚本自备可达基线；未提供时若基线不可达，
  脚本**早退并说清修法**，而不是跑到一半才发现验证不成立
- **拒绝自动处置时只说「没有对应的处置原语」**。运维分不清这是能力缺失还是
  刻意的安全选择，只能自己去翻源码。新增 `NO_AUTO_REMEDIATION_REASON`，
  `anomaly_traffic` 与 `config_error` 各自带上面向使用者的理由
- 顺带清掉随之失去用途的 `rate_mbps` 参数（`heal()` 与 `remediation.build()`）
- **`scripts/lab.sh` 的 sudoers 规则写进了 `/etc/sudoers.d/`，而那个目录从未被读取**。
  该镜像的 sudo 编译时未启用 drop-in，于是 `sudo -n` 一直要密码——而
  `NETMIND_SUDO` 依赖免密提权。改为追加到 `/etc/sudoers` 本体并用 `visudo -c`
  校验（语法写错会让容器里 sudo 整体不可用），起台时打印 `SudoersOK`
- **面板上「丢包率 0.00%」而延迟是 `--`**。真浏览器验证时抓到的：后端返回
  `packet_loss: null`（没采到数据），前端 `Number(metrics.packet_loss || 0)`
  把它变成 0% 并渲染成「丢包率 0.00%」——同一张卡片里延迟显示 `--`、丢包显示
  0%，等于把「没测」说成「测了，是 0」。躲过了前几轮清理是因为 `metricValue`
  守的是 `value` 属性，而这一处躲在模板字符串里做 `* 100` 再 `toFixed`。
  新增 `percentText()`（null 显示 `--`，真实的 0 照实显示 0.00%）并接上；
  同类的 `step.duration_ms || 0` 也改为 null 时显示 `—`。
  门禁 `no-missing-as-zero` 锁死这一类
- **`docker compose up` 之后面板全挂，每个接口 403**。实测：前端页面 200，但
  `/api/system/status`、`/api/dashboard`、`/api/telemetry/latest` 在宿主机经
  `localhost:8000` 访问时一律 403；容器内自访同一路径却 200。原因是后端判
  「本机」看对端是不是 `127.0.0.1`，而经端口映射进来的请求对端是**网关 IP**
  （`172.x.x.1`）——哪怕请求就发自你自己电脑的浏览器。安全模型是对的（默认拒绝），
  错在可发现性：报错只说「请设置 token」，使用者会以为自己已经设过了。
  现三处都点了名：README 快速开始、docs/DEPLOY.md 新增第 0 节、
  docker-compose.yml 变量上方的注释，以及 403 报错正文本身。
  门禁 `container-deploy-needs-token` 锁死
- **「配 token 后只保护非 GET 请求」这句错误说法在三个文档里各留了一份**。
  实际是所有方法含 GET 都要认证：`/api/system/status`、`/api/dashboard`、
  `/api/telemetry/latest` 实测不带 token 均 401。`SECURITY.md` 上一轮已改，
  `docs/API.md` 与 `README.md` 的环境变量表原封不动。门禁 `security-doc-matches-behavior`
  原先只查 `SECURITY.md`——**门禁覆盖了它检查的那份，并不代表别的文档是对的**。
  现扩到全部客户可见文档（README / SECURITY / CHANGELOG / docs/*.md），
  已用「在第三份文档里塞回 non-GET」的反例验证
- **「一切正常」是全项目唯一不经过推导的诊断结论**。异常分支的置信度早已改成按
  证据推导，但 `return Diagnosis(type='normal')` 漏了——吃到 schema 默认的
  confidence=0.9。实测三个后果：样本量 1 与 10 给出同一个 0.9；读数贴阈值
  （45ms vs 50ms 门限）与读数极低（1ms）同样给 0.9；**`sim` 折扣在正常分支
  完全没生效**——模拟数据得出的「一切正常」和真实数据一样自信。
  一个样本都没有时也报 0.9。现按「离阈值多远 × 样本量 × 数据是否真实」推导，
  无样本时返回 0.0 并说明原因。门禁 `no-unearned-confidence` 锁死
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
`scripts/data_ops.py`、`scripts/verify_heal.py`、`scripts/verify_linkdown.py`、
`scripts/ci_audit.py`、
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
