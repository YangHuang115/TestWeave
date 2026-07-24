# Agent Instructions

<!-- TESTWEAVE:EXTERNAL-CLIENT:START -->
## TestWeave External Client

This workspace is connected to TestWeave.

1. Read `.testweave/client/instructions.md`.
2. Read `.testweave/client/project.yaml`.
3. Read the token from the environment variable configured in `.testweave/client/connection.yaml`.
4. Call TestWeave only through HTTP API, MCP, or CLI.
5. Never access the TestWeave database directly.
6. Never modify TestWeave server files.
7. Submit generated content as structured candidate results.
8. Do not approve or publish your own generated results.
9. Do not treat `.testweave/output/` as a platform inbox.
10. On revision or context conflict, reload current state instead of overwriting.
11. Treat the user's first message as workbench input and call `POST /external/v1/workbench/resolve`.
12. Execute `entryPoint` only when the response status is `READY`.
13. The only supported direct entry is `GET /external/v1/tasks/{taskId}` with action `LOAD_TASK_CONTEXT`.
14. For `NEEDS_SELECTION`, `BLOCKED`, or `NOT_FOUND`, show the returned workbench content and wait for the user.
15. Candidate submission must keep `autoPublish=false`; never turn a workbench entry into a publish action.
<!-- TESTWEAVE:EXTERNAL-CLIENT:END -->
