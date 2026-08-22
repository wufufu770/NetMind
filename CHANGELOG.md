# Changelog

All notable changes to NetMind are documented here. Format: [Keep a Changelog](https://keepachangelog.com/); versioning: [SemVer](https://semver.org/).

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
