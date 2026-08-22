# Security Policy

## Threat model

NetMind is a **local-first network operations tool**. Understand what it can touch before you run it:

| Surface | Guarantee |
|---|---|
| Default mode (`NETMIND_DRIVER=simulation`) | No device is ever contacted. All commands are recorded against an in-process simulator. |
| Real drivers (`ssh` / `netconf`) | Commands are **dry-run** until `NETMIND_ENABLE_REAL_COMMANDS=true` is explicitly set alongside credentials. |
| Read-only collection | `collect()` uses napalm/ncclient getters only; it never pushes configuration. |
| Write execution | Always gated by `SecurityChecker` (allowlist + deny-keywords), dangerous commands require the approval workflow (`unattended_policy=deny` default) or are blocked outright. |
| API access | Unset `NETMIND_ADMIN_TOKEN` = open local mode. When set, every non-GET request requires `Authorization: Bearer <token>`. |
| LLM enrichment | Only structured findings JSON leaves the machine, never device configs or credentials. Responses are cached locally under `~/.cache/netmind/`. |

## Known limitations

- The HTTP API has no rate limiting or per-endpoint RBAC. Do not expose it to untrusted networks.
- Rollback paths bypass the "dangerous command" gate by design (they must be able to undo changes); deny-keywords still apply.
- Credentials are provided via environment variables; they are not persisted in the store file.

## Reporting a vulnerability

Open a [security advisory](https://github.com/wufufu770/NetMind/security/advisories/new) rather than a public issue. Expect a response within 7 days.
