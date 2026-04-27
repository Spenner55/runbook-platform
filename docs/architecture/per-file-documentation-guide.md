# Per-File Documentation Guide

The goal is useful documentation close to code without stale noise. Do not add comments to every file by default.

## Module Docstrings

Use module docstrings when a file establishes an architectural boundary, owns non-obvious orchestration, or has constraints future maintainers might violate.

Good candidates:

- Django internal runner views.
- Django AI clients.
- Runner poller/client/executor modules.
- FastAPI parser service.
- Shared frontend API client.

Avoid module docstrings that only restate the filename.

## Class Docstrings

Use class docstrings when a class represents:

- A boundary adapter.
- A stateful orchestrator.
- A schema that is part of an external contract.
- A domain concept with non-obvious invariants.

Skip class docstrings for simple framework config classes unless they explain ownership or safety rules.

## Function Docstrings

Use function docstrings for:

- Service-layer functions with business rules.
- State transitions.
- Transaction boundaries.
- Network/client calls with error translation.
- Parser functions with non-obvious behavior.

Avoid comments like "creates object" when the function name and signature already say that.

## Inline Comments

Inline comments are useful when they explain why code exists, not what Python or TypeScript syntax does.

Useful:

- "The AI call happens outside the DB transaction to avoid holding a connection during network I/O."
- "This endpoint remains separate from the public viewset so runner-only serializers do not leak."

Harmful:

- "Import models."
- "Loop over steps."
- "Return response."

## Subdirectory READMEs

Add or maintain README files in major directories when they explain:

- Ownership.
- Boundary rules.
- Common commands.
- What belongs and does not belong there.

Keep them short. Deep detail belongs in `docs/architecture` or `docs/runbooks`.

## Service-Layer Functions

Document:

- Preconditions.
- State transitions.
- Transaction scope.
- External calls and why they are outside/inside transactions.
- Exceptions raised for domain failures.

Do not document every ORM field assignment unless it is part of a business invariant.

## API Serializers And Views

Serializers:

- Document only contract subtleties, not every field.
- Keep request/response details in API docs.

Views:

- Document boundary or routing choices.
- Keep business explanations in services.

## Runner Modules

Document:

- Polling lifecycle.
- Ownership token handling.
- Heartbeat behavior.
- Failure semantics.
- Prohibited dependencies.

Avoid comments that imply real sandboxed execution exists while the runner still simulates step work.

## Frontend Feature Modules

Document:

- Non-obvious route or cache behavior.
- API boundary rules when a helper could be misused.
- Data-shape assumptions that are not obvious from TypeScript types.

Do not add comments to every hook or component.

## Migrations

Do not add noisy comments to generated migrations.

Add a comment only for unusual migration operations such as:

- Data backfills with assumptions.
- Constraint changes that require manual rollout sequencing.
- Non-reversible operations.

Document migration rationale in architecture docs or PR descriptions.

## Keeping Docs Close Without Stale Noise

- Put stable architecture rules in `docs/architecture`.
- Put operational procedures in `docs/runbooks`.
- Put concise ownership notes in subdirectory READMEs.
- Put only boundary-critical comments in source files.
- Remove or update stale comments when behavior changes.
