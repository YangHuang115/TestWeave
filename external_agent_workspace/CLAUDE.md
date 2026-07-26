# Agent Instructions

<!-- TESTWEAVE:EXTERNAL-CLIENT:START -->
## TestWeave External Client

This workspace is connected to TestWeave.

1. Read `.testweave/client/instructions.md`.
2. Read `.testweave/client/project.yaml`.
3. Read the token from the environment variable configured in `.testweave/client/connection.yaml`.
4. Read the matching `skills/<skill-name>/SKILL.md` for the requested stage; do not rewrite a second stage prompt.
5. Call TestWeave only through HTTP API, MCP, or CLI.
6. Never access the TestWeave database directly.
7. Never modify TestWeave server files.
8. Submit generated content as structured candidate results.
9. Do not approve or publish your own generated results.
10. Do not treat `.testweave/output/` as a platform inbox.
11. On revision or context conflict, reload current state instead of overwriting.
12. Treat the user's first message as workbench input and call `POST /external/v1/workbench/resolve`.
13. Execute `entryPoint` only when the response status is `READY`.
14. The only supported direct entry is `GET /external/v1/tasks/{taskId}` with action `LOAD_TASK_CONTEXT`.
15. For `NEEDS_SELECTION`, `BLOCKED`, or `NOT_FOUND`, show the returned workbench content and wait for the user.
16. Candidate submission must keep `autoPublish=false`; never turn a workbench entry into a publish action.
17. Local Skill use does not require registration; TestWeave Workflow use requires explicit sync and human publication.
<!-- TESTWEAVE:EXTERNAL-CLIENT:END -->
