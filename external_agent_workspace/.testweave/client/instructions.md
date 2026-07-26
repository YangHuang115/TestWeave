# TestWeave External Client Instructions

- The server Token Scope is authoritative.
- Local permissions files cannot elevate access.
- Read platform data only when needed.
- Do not keep a permanent mirror of TestWeave project data.
- Generated results must match the declared Artifact Schema.
- Include Base Revision, Context Hash, and Idempotency Key.
- Upload files through the file API.
- The platform never scans `.testweave/output/`.
- High-risk actions require Web Client confirmation.
