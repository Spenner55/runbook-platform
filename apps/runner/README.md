# Runner Service

Python worker responsible for polling for approved executions and running workflow steps.

## Current Scope
- Basic long-running worker entrypoint
- Placeholder modules for sandboxing, logging, upload, and API client behavior

## Next Steps
- Replace heartbeat loop with execution polling
- Add sandbox execution boundaries and artifact upload flow
- Add structured logging and retry handling
