# Infra Scripts

Use this directory for local bootstrap, deployment, and environment helper scripts once operator workflows are defined.

Scripts added here should:

- Be documented in a runbook.
- Avoid storing secrets.
- Avoid duplicating Makefile targets unless there is a clear reason.
- Prefer Docker-first execution for local developer workflows.
