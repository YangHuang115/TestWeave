# Agent Instructions

<!-- TESTWEAVE:EXTERNAL-CLIENT:START -->
## TestWeave External Client

This workspace is local-first; connecting to TestWeave is optional.

1. Default to local mode: load skills directly from `skills/<skill-name>/`, no token, no registration, no sync, no publication, and no HTTP requests.
2. The stage order and human confirmation points are defined in `capabilities/ai-test-design/workflow.yaml`; do not hardcode the flow.
3. Persist local stage outputs as chained records under `runs/` via `run_agent.py` (`--record-start` / `--record-submit` / `--record-approve` / `--record-reject` / `--record-resume`).
4. Only when the user explicitly chooses connected or share mode: read `.testweave/client/instructions.md`, `.testweave/client/project.yaml` (if present), and the token from `.env.local` or the environment variable configured in `.testweave/client/connection.yaml`.
5. Read the matching `skills/<skill-name>/SKILL.md` for the requested stage; do not rewrite a second stage prompt.
6. Call TestWeave only through HTTP API, MCP, or CLI, and only in connected/share mode.
7. Never access the TestWeave database directly.
8. Never modify TestWeave server files.
9. Submit generated content as structured candidate results.
10. Do not approve or publish your own generated results; publication requires a Web user with `agent.manage`.
11. Do not treat `.testweave/output/` as a platform inbox.
12. On revision or context conflict, reload current state instead of overwriting.
13. In connected mode, when the user's first message is workbench input, call `POST /external/v1/workbench/resolve`.
14. Execute `entryPoint` only when the response status is `READY`.
15. The only supported direct entry is `GET /external/v1/tasks/{taskId}` with action `LOAD_TASK_CONTEXT`.
16. For `NEEDS_SELECTION`, `BLOCKED`, or `NOT_FOUND`, show the returned workbench content and wait for the user.
17. Candidate submission must keep `autoPublish=false`; never turn a workbench entry into a publish action.
18. Sharing is an explicit, separate operation (`--mode share` → `POST /external/v1/skills/sync-draft`, `skill:sync` scope, produces `SYNCED_DRAFT` only); never auto-sync in connected mode.
19. Local Skill use does not require registration; TestWeave Workflow use requires explicit sync and human publication.
<!-- TESTWEAVE:EXTERNAL-CLIENT:END -->
