# NetMind API Summary

Auth: set `NETMIND_ADMIN_TOKEN` to require `Authorization: Bearer <token>` on all non-GET requests. Unset (default) = open local mode.

Interactive docs: `/docs` · OpenAPI: `/openapi.json`

## System
GET `/` — service info
GET `/api/system/status`
POST `/api/system/model-health-check`
GET `/api/readiness`
GET `/api/notifications`
WS `/ws/events`

## Intent loop
POST `/api/intent/parse` — NL → IntentDSL
POST `/api/intent/submit` — full closed loop
POST `/api/intent/compile`
POST `/api/intent/resolve-ambiguity`
POST `/api/workflows/run` — same as submit with workflow id
GET `/api/executions` · GET `/api/executions/{id}` · GET `/api/executions/{id}/replay` · GET `/api/executions/{id}/tool-sequence`

## Policy & deployment
POST `/api/planner/plan`
POST `/api/verification/check`
GET `/api/policy/conflict-matrix` · POST `/api/policy/{execution_id}/auto-fix`
POST `/api/deploy/{execution_id}` (mode: `simulated` | `dry-run` | `real`)
GET `/api/deploy/{execution_id}/rollback-plan` · POST `/api/deploy/{execution_id}/rollback`
GET `/api/security/check?command=...`
GET `/api/drivers`

## Approvals
POST/GET `/api/approvals` · POST `/api/approvals/{id}/{approved|rejected}`
POST `/api/approval-requests/from-execution/{execution_id}`
POST `/api/approval-requests/{id}/execute`

## Telemetry
GET `/api/telemetry/latest` · GET `/api/telemetry/history`
GET `/api/telemetry/anomaly` · GET `/api/telemetry/predict-sla`
POST `/api/experiment/fault` · POST `/api/experiment/scenario/{name}`
POST `/api/telemetry/diagnose` · POST `/api/telemetry/heal`

## Topology
GET `/api/topology` · GET `/api/topology/reachable` · GET `/api/topology/nodes/{node_id}`

## Agents & chat
GET `/api/agents` · GET `/api/agents/executions/{execution_id}`
POST `/api/chat/ask` (read-only) · POST `/api/agents/chat`
GET/PUT `/api/config/agents/{name}/schedule`

## Tools gateway
GET `/api/tools` · POST `/api/tools/call`
GET `/api/mcp/list_tools` · POST `/api/mcp/call_tool`

## Config
GET `/api/config/export` (.yaml variant) · POST `/api/config/import` (.yaml variant)
POST `/api/config/validate` · POST `/api/config/reset-runtime`
GET/POST `/api/config/models` (+ `/test`, `/call-history`, `/presets`, DELETE, bind-agent)
GET/POST/DELETE `/api/config/agents` (+ `/prompts/recommended`)
GET/POST `/api/config/rules` (+ `/rules/test`) · GET/POST `/api/config/tools`
GET/POST/DELETE `/api/config/workflows`
GET/POST/DELETE `/api/config/credentials`
GET/PUT `/api/config/theme` · `/config/fonts` · `/config/security`
GET/POST `/api/config/mcp-servers/{name}`

## Templates
GET `/api/templates` · POST `/api/templates/suggest`
CRUD `/api/templates/manage/*` (alias `/api/template-manager/*`)

## Logs & reports
GET `/api/logs` · GET `/api/logs/search` · GET `/api/audit/summary`
POST `/api/report/generate` → md
GET `/api/report/{id}.md|.json|.html|.pdf|/bundle|/rich.html|/rich.pdf`

## LangGraph adapter
GET `/api/langgraph/graph` · POST `/api/langgraph/run?require_approval=true`
GET `/api/langgraph/interrupts` · POST `/api/langgraph/resume/{interrupt_id}`
