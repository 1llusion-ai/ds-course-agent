# API App

This directory now hosts the primary FastAPI implementation.

Current state:

- `apps/api/app/` is the active runtime entrypoint
- `backend/app/` is kept as a compatibility shim for older imports and tests
- `backend/tests/` still holds API integration tests during the transition

Long-term target:

```text
apps/api/app/
apps/api/tests/
```
