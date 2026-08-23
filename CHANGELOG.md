# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Security
- Dangerous-op gate is semantic: any `del-flows` / `mod-flows` / `iptables -F` / `ip link set down` / `ip route del` / `ip addr del` requires the approval workflow regardless of target device (was: hardcoded `s1` prefix match let `del-flows s2` through).
- Rollback privilege now requires a server-issued flow cookie: TransactionManager registers every planned cookie at deploy time; forged or foreign cookies on rollback commands fall through to the gate instead of executing.
- POST `/api/deploy/{id}/rollback` actually executes the plan through the driver with per-command checks and honest per-command results; returns 409 when the execution was never deployed.

### Changed
- `DeployResult.rollback_complete` distinguishes a fully successful auto-rollback from a partial attempt (`rolled_back` stays "attempted").
- tc interface-name strictness applies to simulation only; ssh/netconf real-device drivers accept standard interface names.
- Dashboard manual deploy panel derives `security_passed` from per-command results and `rollback_ready` from the actual rollback plan instead of hardcoding success.

### Removed
- Committed `backend/build` artifacts from the repository; `.gitignore` now covers `build/`.

### Tests
- Eval-round test files renamed by subject under test (e.g. `test_round4_reports_store.py` → `test_reports_store.py`, `test_complete_final.py` → `test_api_smoke.py`).
- New regression suite `test_security_gate_semantics.py`: gate bypass probes, cookie-registry flow, closed-loop rollback integration.

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
