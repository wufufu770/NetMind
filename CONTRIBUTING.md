# Contributing

Thanks for your interest in NetMind. This project keeps a small, honest surface area — read the rules below before opening a PR.

## Ground rules

1. **The honesty table is contractual.** `README.md` contains a "What's real / What's simulated" table. Any PR that moves a capability between states must update that table in the same commit.
2. **No fabricated telemetry.** Durations must be measured, confidences derived from observable state (see `app/core/verification.py` for the pattern). Tests that assert invented constants will be rejected.
3. **Deterministic core, thin adapters.** Business logic lives as pure functions (`core/`, `diagnose/`); routers and CLI are adapters. No business logic inside route handlers.
4. **No comments unless asked** — code should read itself; docstrings only where they carry non-obvious contracts.

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
- New behavior has tests; honesty table updated if applicable
- Frontend changes: `npm ci && npm run build` passes

## Commit style

Short imperative subject, body explains *why*. One logical change per commit.

## License

By contributing you agree your work is released under the repository's MIT license.
