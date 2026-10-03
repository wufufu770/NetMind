# Security Policy

## Threat model

NetMind is a **local-first network operations tool**. Understand what it can touch before you run it.

| Surface | Guarantee |
|---|---|
| Default mode (`NETMIND_DRIVER=simulation`) | No device is ever contacted. All commands are recorded against an in-process simulator. |
| Real drivers (`ssh` / `netconf`) | Commands are **dry-run** until `NETMIND_ENABLE_REAL_COMMANDS=true` is explicitly set alongside credentials. |
| Read-only collection | `collect()` uses napalm/ncclient getters only; it never pushes configuration. |
| Write execution | Gated by `SecurityChecker`: allowlist + deny-keywords, plus a per-command interface policy. Dangerous commands (`del-flows` / `mod-flows` / `iptables -F` / `link set down` / `route del` / `addr del`) are blocked outright under the default `unattended_policy=deny`. |
| Auto-remediation | **Off unless `NETMIND_HEAL_IFACE` is set.** The interface is never guessed, and repeated failures against the same fault stop at a cap (default 3) and hand off to a human. See `docs/DEPLOY.md` §8. |
| API access | With no `NETMIND_ADMIN_TOKEN` set, **only loopback** can reach the API; everything else gets 403. Once the token is set, **every** method on **every** endpoint requires `Authorization: Bearer <token>` — including GET. `/healthz` is the sole public exception. |
| LLM egress | Leaving the machine: the intent text, the IntentDSL, and a tool context built from topology, telemetry, path, and SLA/bandwidth estimates. **Not** sent: device credentials, persisted store contents, command history. Cached to `~/.cache/netmind/` on the diagnose/enhance path only (override with `NETMIND_CACHE_DIR`); the main model adapter keeps history in memory. |

## Known limitations

These are real gaps, not disclaimers. If one of them blocks your deployment, say so in an issue.

- **No per-endpoint RBAC.** Anyone holding the admin token has every permission.
  For a self-hosted single-operator install one admin token is a workable model; for a
  shared or multi-operator deployment it is not — you would be handing the same key to
  people who should see different things. There is no read-only role.
- **Rate limiting is in-process only.** Per-source token buckets (write 5/s, read 50/s;
  `NETMIND_RATE_LIMIT=off` disables them for bulk import) live in the worker process,
  so a multi-worker deployment multiplies the effective limit. See `docs/DEPLOY.md` §3, §6.5.
- **Rollback does not bypass the dangerous-command gate.** It runs the same check with
  `allow_dangerous=True`, and that still demands proof of ownership: flow commands must
  carry a NetMind cookie registered at dispatch time, and `ip route del` must name a
  route this system added with `ip route add` (routes carry no cookie, so ownership is
  tracked in a registry — the command text is forgeable, the registration is not).
  Anything else stays blocked.
- **`congestion` remediation cannot be rolled back.** It removes a queue-shaping rule
  the tool did not create and did not record, so no equivalent inverse can be built. The
  report says "cannot roll back automatically" rather than pretending otherwise.
- **Single worker required.** The store is one JSON file guarded by an in-process
  `RLock`; running more than one worker risks lost writes. `docs/DEPLOY.md` §3.
- **Credentials live in the store as masked references**: `secret_ref` values are
  redacted (`***`) in the persisted JSON and in every read endpoint. Point `secret_ref`
  at your vault path and supply real secrets through environment variables at runtime.

## Response commitments

| Stage | Target |
|---|---|
| Acknowledgement of a report | 7 days |
| Triage (severity assigned, reproduction attempted) | 14 days |
| Fix or documented mitigation for confirmed high/critical | 30 days |
| Fix for confirmed medium | 90 days |
| Fix for confirmed low | next release |

These are targets, not guarantees — but they are commitments, and missing them is a
bug in this policy that you can hold us to. Reports are tracked in the public
advisory once a fix ships, unless you ask us to keep it private while a fix is prepared.

Not yet provided, and we would rather say so than imply coverage we do not have:
a formal CVE assignment, a bug-bounty programme, or a signed release artifact.

## Reporting a vulnerability

Open a [security advisory](https://github.com/wufufu770/NetMind/security/advisories/new)
rather than a public issue.
