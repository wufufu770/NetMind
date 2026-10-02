# Contributing

Thanks for your interest in NetMind. This project keeps a small, honest surface area — read the rules below before opening a PR.

## Ground rules

1. **The honesty table is contractual.** `README.md` contains a "What's real / What's simulated" table. Any PR that moves a capability between states must update that table in the same commit.
2. **No fabricated telemetry.** Durations must be measured, confidences derived from observable state (see `app/core/verification.py` for the pattern). Tests that assert invented constants will be rejected.
3. **Deterministic core, thin adapters.** Business logic lives as pure functions (`core/`, `diagnose/`); routers and CLI are adapters. No business logic inside route handlers.
4. **No comments unless asked** — code should read itself; docstrings only where they carry non-obvious contracts.
5. **Marketing claims are verifiable.** This is rule 2 extended from code to anything a reader outside the repo can see. Every claim in `README.md`, `docs/`, the changelog, and any future landing/pricing page must attach something the reader can reproduce: a command, a report, a benchmark, a commit SHA. A claim that cannot be attached is deleted. "We have no public case studies yet" is a valid sentence; a fabricated one is not. `python3 scripts/copy_lint.py` is the mechanical gate — it flags hollow marketing vocabulary, unsourced numbers, meta-commentary, decorative emoji, and over-formatting.

## Iteration protocol

Development runs on an explicit loop: BUILD → TEST → IMPROVE → PLAN → STATE. Each round ships one verifiable increment, every gate declares how it fails (`block` / `autofix` / `rollback` / `warn`), and `state.json` always holds a non-empty backlog so there is always a next step.

```bash
python3 scripts/loop.py status     # cycle, phase, metrics, next round
python3 scripts/loop.py gates      # run gates only
python3 scripts/loop.py round      # test → improve → plan → state
```

Design rationale: `.netmind-loop/protocol.md`. Machine-readable state: `.netmind-loop/state.json`.

## Development setup

```bash
git clone https://github.com/wufufu770/NetMind && cd NetMind
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: pip install -r requirements.txt
pytest -q
python ../scripts/validate_project.py
```

Optional extras:

```bash
pip install -e ".[drivers]"      # napalm/netmiko/ncclient for live collection
```

## Before opening a PR

- `pytest -q` green (CI runs 3.10–3.12)
- `scripts/validate_project.py` exits 0
- `python3 scripts/loop.py gates` passes (includes the copy gate from rule 5)
- New behavior has tests; honesty table updated if applicable
- Frontend changes: `npm ci && npm run build` passes

## Commit style

Short imperative subject, body explains *why*. One logical change per commit.

## License

By contributing you agree your work is released under the repository's MIT license (`LICENSE`).

Contributions also require a Developer Certificate of Origin sign-off (`git commit -s`). See `CLA.md` — this is still a draft pending legal review, and it matters because accepted contributions cannot be re-licensed retroactively without one.

