# NetMind API Summary

## Core
GET /api/system/status
GET /api/dashboard
POST /api/intent/parse
POST /api/intent/submit
GET /api/executions
GET /api/executions/{id}/replay

## Policy
POST /api/planner/plan
POST /api/verification/check
GET /api/deploy/{id}/rollback-plan
POST /api/deploy/{id}

## Telemetry
GET /api/telemetry/latest
GET /api/telemetry/history
POST /api/experiment/fault
POST /api/telemetry/diagnose
POST /api/telemetry/heal

## Config
GET /api/config/export
GET /api/config/export.yaml
POST /api/config/import
GET/POST /api/config/models
GET/POST /api/config/agents
GET/POST /api/config/rules
GET/POST /api/config/tools
GET/POST /api/config/workflows
GET/POST /api/config/credentials

## Runtime
GET /api/readiness
GET /api/audit/summary
POST /api/tools/call
POST /api/workflows/run
GET /api/topology/nodes/{node_id}
GET /api/logs/search
