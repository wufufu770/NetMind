# Launch draft — Show HN / r/networking (EN)

> Status: DRAFT — do not post until you approve. Posting is manual.

**Title (HN):** Show HN: NetMind – intent-driven network diagnosis and rollback-safe changes

**Body:**

Hi HN, I built NetMind, an open-source (MIT) network operations agent that turns natural-language intents into verified, rollback-safe policy changes — the "k8sgpt for networks" that I couldn't find.

Why: K8s got k8sgpt and HolmesGPT for AI-assisted diagnostics; networking has nothing comparable in open source. Meanwhile Gartner already names "agentic NetOps" as an emerging category, so the commercial world is moving — the OSS equivalent is missing.

What it does today:

- `netmind diagnose <containerlab.yml>` validates topologies without deploying: dangling endpoints, IP conflicts, isolation groups, invalid mgmt addresses. Optional `--live` collects interface state via napalm; optional `--llm` adds root-cause analysis (DeepSeek/OpenAI/Ollama, responses cached locally).
- An intent closed loop: natural language → DSL → plan → semantic conflict check → security allowlist → human approval → transactional deploy with rollback plans → telemetry → heal.
- Honesty-first design: every deploy result carries an explicit mode (`simulated` / `dry-run` / `real`); telemetry snapshots are labelled with their source; real devices are touched only behind two explicit gates (`NETMIND_DRIVER=ssh` + `NETMIND_ENABLE_REAL_COMMANDS=true`).

Stack: FastAPI + React + LangGraph adapter + MCP-style tool registry. ~3k lines backend, 50 tests, CI on 3.10–3.12.

Repo: https://github.com/wufufu770/NetMind

Roadmap: guardrailed healing loop next (config diff → pre-verify → approve → apply → post-verify), then a real MCP server so coding agents can operate networks safely.

Roast welcome — especially on the verifier design (semantic conflict matching) and what checks you'd want in `diagnose`.

---

# Launch draft — 掘金 / V2EX (CN)

> 状态：草稿，发布前需你确认。发布动作由你手动执行。

**标题：** 开源了一个"网络版的 k8sgpt"：netmind，用自然语言做网络诊断与回滚安全的变更

**正文：**

做了个开源项目 NetMind（MIT），定位一句话：给网络运维补上 k8s 那边 k8sgpt/HolmesGPT 的生态位——意图驱动的诊断 + 回滚安全的变更闭环。

现在能干什么：

1. `netmind diagnose <containerlab拓扑>` 不部署就体检：悬空链路端点、IP 冲突、拓扑隔离、非法管理地址；加 `--live` 用 napalm 采接口状态；加 `--llm` 出根因分析（DeepSeek/Ollama 可选，本地缓存，不发设备配置）。
2. 意图闭环：自然语言 → DSL → 规划 → 语义冲突检测（QoS×ACL）→ 安全白名单 → 人工审批 → 事务下发+回滚计划。
3. 设计原则是"诚实"：每个下发结果带 mode 字段（simulated/dry-run/real），遥测快照标注来源，碰真设备需要两道显式开关——默认永远不碰生产。

技术栈 FastAPI + React + LangGraph 适配器，后端 3k 行、50 个测试、CI 三版本矩阵。

仓库：https://github.com/wufufu770/NetMind

求拍砖，尤其想听：diagnose 还该加哪些检查项？验证器的语义冲突规则哪里设计得不对？
