# Pilot Phase B: Typed Actions and Workflow Schema v2 Blueprint

| Field | Value |
|---|---|
| Blueprint ID | `pilot-phase-b-typed-actions-workflow-schema-v2` |
| Objective | Define a typed, versioned workflow schema and action catalog suitable for safe pilot execution. |
| Status | Blueprint only |
| Authored | 2026-05-08 |
| Primary gap | `packages/workflow-schema/workflow.schema.json` is too generic: step `type` is an unconstrained string, action inputs are not typed, secrets and artifacts are not declared, and runner dispatch cannot fail closed from a stable action contract. |
| Depends on | Current workflow, execution, approval, policy, audit, artifact, AI parsing, and runner scaffolding; Pilot Phase A execution substrate for real `shell_command` execution. |

## 1. Workflow Schema v2 Goals

Workflow schema v2 must turn workflow definitions from generic step lists into explicit execution contracts.

Primary goals:

- Preserve Django as the control plane and state authority.
- Preserve the runner boundary: runner talks only to Django internal APIs.
- Make every executable step dispatchable by a typed action contract.
- Make unsupported, ambiguous, or unsafe actions fail before execution.
- Give policy, approvals, audit, evidence, and UI enough structured facts to reason about the intended action.
- Declare secrets by reference only; raw secret values must never appear in workflow JSON, execution snapshots, logs, artifacts, policy evaluations, audit metadata, or AI parse records.
- Declare expected artifacts before execution so evidence completeness can be validated.
- Define timeout, retry, idempotency, and dry-run behavior explicitly per step.
- Keep existing v1 workflows executable while v2 is introduced.
- Keep action contracts versioned and immutable once workflows can reference them.

The v2 design should not try to solve the full future action universe. It should support a narrow pilot catalog and provide a clean path for later actions such as Terraform, Kubernetes, database migration, and cloud-provider operations.

## 2. Current State Summary

Files inspected for this blueprint:

- `packages/workflow-schema/workflow.schema.json`
- `packages/contracts/workflow/workflow.schema.json`
- `apps/api/apps/workflows/models.py`
- `apps/api/apps/workflows/services.py`
- `apps/api/apps/workflows/internal_clients.py`
- `apps/api/apps/executions/models.py`
- `apps/api/apps/executions/services.py`
- `apps/api/apps/executions/internal_serializers.py`
- `apps/api/apps/executions/internal_views.py`
- `apps/api/apps/policies/models.py`
- `apps/api/apps/policies/services.py`
- `apps/api/apps/artifacts/models.py`
- `apps/api/apps/artifacts/services.py`
- `apps/runner/runner/schemas.py`
- `apps/runner/runner/executor.py`
- `apps/runner/runner/sandbox.py`
- `apps/runner/runner/artifact_uploader.py`
- `apps/web/src/features/workflows/types.ts`
- `apps/web/src/features/executions/types.ts`
- `docs/report/real-world-readiness-after-phase-11-6.md`
- `docs/blueprints/phase-10-06-richer-ai-parsing-blueprint.md`

Important current facts:

- `Workflow.definition_schema_version` already exists and defaults to `workflow.schema.v1`.
- `Workflow.definition` is a JSONField and can store a v2 object without a database shape change.
- v1 schema requires only workflow `name` and `steps`; each step requires `id`, `name`, `type`, and `risk`.
- `apps/api/apps/workflows/services.py` already validates v1 schema plus semantic constraints for supported step types and risks.
- Current supported v1 step types are `manual_task`, `shell_command`, and `approval`.
- `Execution.workflow_snapshot` stores an immutable copy of the workflow definition.
- `ExecutionStep.step_snapshot` stores the per-step source object.
- `ExecutionStep` currently has denormalized fields: `step_key`, `name`, `step_type`, `risk_level`, `command`, and `requires_approval`.
- The runner claim payload currently exposes only generic step fields, not the full `step_snapshot`.
- Every runner step calls Django's step-start gate before execution.
- Policy currently evaluates `risk_level`, `step_type`, and time window.
- Artifact upload already flows through Django internal APIs and records checksum, kind, name, MIME type, size, storage key, runner ID, and metadata.
- `apps/runner/runner/executor.py` still simulates work today; Pilot Phase A is expected to replace that with a sandbox provider.

## 3. Backward Compatibility Strategy

v2 must be additive.

Rules:

- Existing v1 workflows keep `definition_schema_version="workflow.schema.v1"` and keep their current `definition` shape.
- Existing execution snapshots are immutable and must never be rewritten.
- `create_execution()` must branch validation and materialization by `workflow.definition_schema_version`.
- Internal runner serializers must support v1 and v2 during migration.
- v1 runner behavior remains until v1 workflows are retired.
- v2-only features such as dry-run mode, declared secrets, declared artifacts, and action-specific inputs are not backported into v1 definitions.
- The UI may offer a "Create v2 draft from v1" migration action, but it must create a new workflow version rather than mutating the original.

Compatibility matrix:

| Workflow schema | Create execution | Runner claim | Runner execution | Migration |
|---|---:|---|---|---|
| `workflow.schema.v1` | Supported | Existing generic fields | Existing v1 compatibility handler | Optional lifted draft |
| `workflow.schema.v2` | Supported after validators ship | Generic fields plus `action_snapshot` | Typed action dispatch | Native |
| Unknown schema | Rejected | Not claimed | Not executed | Not applicable |

## 4. Typed Action Model

Schema v2 uses a stable workflow envelope and a typed action invocation per step.

Top-level shape:

```json
{
  "schemaVersion": "workflow.schema.v2",
  "name": "Deploy service",
  "description": "Pilot-safe deployment workflow",
  "catalogVersion": "pilot.v1",
  "defaults": {
    "timeoutSeconds": 300,
    "retry": {
      "maxAttempts": 1
    }
  },
  "secrets": [],
  "steps": []
}
```

Step shape:

```json
{
  "id": "deploy",
  "name": "Deploy service",
  "type": "shell_command",
  "risk": "high",
  "requiresApproval": true,
  "approvalTimeoutSeconds": 1800,
  "action": {
    "type": "shell_command",
    "version": "pilot.v1",
    "inputs": {},
    "outputs": {}
  },
  "timeoutSeconds": 600,
  "retry": {
    "maxAttempts": 1
  },
  "idempotency": {
    "mode": "none"
  },
  "dryRun": {
    "supported": true,
    "strategy": "validate_only"
  },
  "artifacts": []
}
```

Design rules:

- `step.type` remains the policy-facing and execution-step-facing type.
- `step.action.type` is the dispatch-facing action type.
- Semantic validation requires `step.type == step.action.type`.
- `step.action.version` identifies an immutable action contract.
- Action handlers validate `step.action.inputs` against the matching action input schema.
- `step.action.outputs` declares structured output facts produced by the handler, not raw log streams.
- Per-step `artifacts` declares files or reports expected from the action.
- Per-step `secrets` references top-level secret declarations by key.
- Per-step `timeoutSeconds`, `retry`, `idempotency`, and `dryRun` override top-level defaults.

## 5. Supported Pilot-Safe Action Types

The initial pilot catalog should be deliberately small.

| Action type | Side effects | Runner execution | Pilot status |
|---|---|---|---|
| `manual_task` | Human/operator only | No command execution | Supported |
| `approval_gate` | Control-plane approval only | No command execution | Supported |
| `shell_command` | Local runner host or reachable targets | Sandbox provider from Phase A | Supported with strict limits |
| `http_request` | External service request | Runner HTTP client, no shell | Supported with allowlists and method limits |
| `artifact_assertion` | None | Validate uploaded/declared artifacts | Supported |

Pilot restrictions:

- Unknown action types are invalid at draft validation, publish validation, execution creation, and runner dispatch.
- `shell_command` requires a non-empty command spec, timeout, idempotency declaration, and artifact path validation.
- `http_request` requires an allowlisted URL pattern, bounded response size, timeout, and method-specific idempotency rules.
- `manual_task` and `approval_gate` must not contain shell commands or secret injections.
- `artifact_assertion` can read artifact metadata and checksums from Django, but must not access arbitrary runner filesystem paths.

Explicitly deferred action types:

- `terraform_plan`
- `terraform_apply`
- `kubernetes_rollout`
- `database_migration`
- `cloud_aws_cli`
- `script`
- `ansible_playbook`
- `pagerduty_event`
- `servicenow_change_update`

These deferred action types should only be added when their contracts, target model, credential model, dry-run semantics, and evidence requirements are understood.

## 6. Action Input and Output Schemas

Action schemas should live beside the canonical workflow schema.

Proposed files:

- `packages/workflow-schema/workflow.v2.schema.json`
- `packages/workflow-schema/action-catalog.pilot.v1.json`
- `packages/workflow-schema/actions/manual_task.pilot.v1.schema.json`
- `packages/workflow-schema/actions/approval_gate.pilot.v1.schema.json`
- `packages/workflow-schema/actions/shell_command.pilot.v1.schema.json`
- `packages/workflow-schema/actions/http_request.pilot.v1.schema.json`
- `packages/workflow-schema/actions/artifact_assertion.pilot.v1.schema.json`
- `packages/contracts/workflow/workflow.v2.schema.json`

`packages/workflow-schema` should remain the canonical runtime validation source used by Django. `packages/contracts` can mirror the schema for SDK/documentation consumers if that package remains in use.

### 6.0 Workflow v2 JSON Schema Excerpt

This is an illustrative excerpt, not the full schema.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WorkflowDefinitionV2",
  "type": "object",
  "additionalProperties": false,
  "required": ["schemaVersion", "name", "catalogVersion", "steps"],
  "properties": {
    "schemaVersion": {
      "const": "workflow.schema.v2"
    },
    "name": {
      "type": "string",
      "minLength": 1,
      "maxLength": 255
    },
    "description": {
      "type": "string"
    },
    "catalogVersion": {
      "type": "string",
      "enum": ["pilot.v1"]
    },
    "defaults": {
      "$ref": "#/definitions/defaults"
    },
    "secrets": {
      "type": "array",
      "items": {
        "$ref": "#/definitions/secretDeclaration"
      },
      "default": []
    },
    "steps": {
      "type": "array",
      "minItems": 1,
      "items": {
        "$ref": "#/definitions/step"
      }
    }
  },
  "definitions": {
    "step": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "name", "type", "risk", "action"],
      "properties": {
        "id": {
          "type": "string",
          "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$"
        },
        "name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 255
        },
        "type": {
          "enum": [
            "manual_task",
            "approval_gate",
            "shell_command",
            "http_request",
            "artifact_assertion"
          ]
        },
        "risk": {
          "enum": ["low", "medium", "high", "critical"]
        },
        "requiresApproval": {
          "type": "boolean",
          "default": false
        },
        "approvalTimeoutSeconds": {
          "type": "integer",
          "minimum": 1
        },
        "action": {
          "$ref": "#/definitions/actionInvocation"
        },
        "timeoutSeconds": {
          "type": "integer",
          "minimum": 1,
          "maximum": 86400
        },
        "retry": {
          "$ref": "#/definitions/retry"
        },
        "idempotency": {
          "$ref": "#/definitions/idempotency"
        },
        "dryRun": {
          "$ref": "#/definitions/dryRun"
        },
        "secrets": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "default": []
        },
        "artifacts": {
          "type": "array",
          "items": {
            "$ref": "#/definitions/artifactDeclaration"
          },
          "default": []
        }
      }
    },
    "actionInvocation": {
      "type": "object",
      "additionalProperties": false,
      "required": ["type", "version", "inputs"],
      "properties": {
        "type": {
          "type": "string"
        },
        "version": {
          "type": "string"
        },
        "inputs": {
          "type": "object"
        },
        "outputs": {
          "type": "object",
          "default": {}
        }
      }
    },
    "retry": {
      "type": "object",
      "additionalProperties": false,
      "required": ["maxAttempts"],
      "properties": {
        "maxAttempts": {
          "type": "integer",
          "minimum": 1,
          "maximum": 10
        },
        "backoffSeconds": {
          "type": "integer",
          "minimum": 0,
          "default": 0
        },
        "retryOn": {
          "type": "array",
          "items": {
            "enum": [
              "runner_transient",
              "network_transient",
              "timeout",
              "rate_limited"
            ]
          },
          "default": []
        }
      }
    },
    "idempotency": {
      "type": "object",
      "additionalProperties": false,
      "required": ["mode"],
      "properties": {
        "mode": {
          "enum": ["none", "natural", "keyed", "external"]
        },
        "key": {
          "type": "string"
        },
        "reason": {
          "type": "string"
        }
      }
    },
    "dryRun": {
      "type": "object",
      "additionalProperties": false,
      "required": ["supported", "strategy"],
      "properties": {
        "supported": {
          "type": "boolean"
        },
        "strategy": {
          "enum": ["native", "validate_only", "mock", "unsupported"]
        },
        "requiresSecrets": {
          "type": "boolean",
          "default": false
        }
      }
    }
  }
}
```

### 6.0.1 Action Catalog Example

```json
{
  "catalogVersion": "pilot.v1",
  "actions": [
    {
      "type": "shell_command",
      "version": "pilot.v1",
      "inputSchema": "actions/shell_command.pilot.v1.schema.json",
      "runnerCapabilities": ["sandbox.local_process"],
      "mutatesTargetByDefault": true,
      "supportsDryRun": true
    },
    {
      "type": "http_request",
      "version": "pilot.v1",
      "inputSchema": "actions/http_request.pilot.v1.schema.json",
      "runnerCapabilities": ["http.client"],
      "mutatesTargetByDefault": false,
      "supportsDryRun": true
    }
  ]
}
```

### 6.0.2 Shell Command Action JSON Schema Excerpt

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ShellCommandActionPilotV1",
  "type": "object",
  "additionalProperties": false,
  "required": ["commandMode"],
  "properties": {
    "commandMode": {
      "enum": ["argv", "shell"]
    },
    "argv": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "string"
      }
    },
    "command": {
      "type": "string",
      "minLength": 1
    },
    "workingDirectory": {
      "type": "string",
      "default": "."
    },
    "environment": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      },
      "default": {}
    },
    "secretEnvironment": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      },
      "default": {}
    }
  }
}
```

### 6.1 Shell Command Input Example

```json
{
  "type": "shell_command",
  "version": "pilot.v1",
  "inputs": {
    "commandMode": "argv",
    "argv": ["./deploy.sh", "--service", "api", "--env", "staging"],
    "workingDirectory": ".",
    "environment": {
      "DEPLOY_ENV": "staging"
    },
    "secretEnvironment": {
      "DEPLOY_TOKEN": "deploy_api_token"
    }
  },
  "outputs": {
    "exitCode": {
      "type": "integer"
    },
    "stdoutSummary": {
      "type": "string",
      "maxLength": 2048
    }
  }
}
```

Validation rules:

- `commandMode` is `argv` or `shell`.
- `argv` is required when `commandMode="argv"`.
- `command` is required when `commandMode="shell"`.
- Shell mode is allowed only when the runner pool and policy permit it.
- `workingDirectory` must be relative and must not contain `..`.
- `environment` values must be strings and must not contain secret-looking values.
- `secretEnvironment` maps environment variable names to declared secret keys.

### 6.2 HTTP Request Input Example

```json
{
  "type": "http_request",
  "version": "pilot.v1",
  "inputs": {
    "method": "GET",
    "url": "https://status.example.com/api/health",
    "headers": {
      "Accept": "application/json"
    },
    "secretHeaders": {},
    "body": null,
    "expectedStatus": [200],
    "responseMaxBytes": 1048576
  },
  "outputs": {
    "statusCode": {
      "type": "integer"
    },
    "jsonPathAssertions": [
      {
        "path": "$.status",
        "equals": "ok"
      }
    ]
  }
}
```

Validation rules:

- `url` must be absolute HTTPS unless an explicit runner-pool allowlist permits HTTP for local development.
- Host must match organization or runner-pool egress allowlists.
- `GET`, `HEAD`, and `OPTIONS` are idempotent by default.
- `POST`, `PUT`, `PATCH`, and `DELETE` require `requiresApproval=true`, an idempotency declaration, and policy eligibility.
- Response body capture is capped.
- Secret headers reference declared secrets by key.

### 6.3 Manual Task Input Example

```json
{
  "type": "manual_task",
  "version": "pilot.v1",
  "inputs": {
    "instructions": "Verify the deployment window is still open.",
    "completionRequired": true
  },
  "outputs": {
    "operatorNoteRequired": false
  }
}
```

### 6.4 Approval Gate Input Example

```json
{
  "type": "approval_gate",
  "version": "pilot.v1",
  "inputs": {
    "reason": "Production deployment approval",
    "minApprovals": 1,
    "timeoutSeconds": 1800
  },
  "outputs": {
    "approvalRequestId": {
      "type": "string",
      "format": "uuid"
    }
  }
}
```

### 6.5 Artifact Assertion Input Example

```json
{
  "type": "artifact_assertion",
  "version": "pilot.v1",
  "inputs": {
    "requiredArtifacts": ["deploy_manifest"],
    "checksumRequired": true
  },
  "outputs": {
    "matchedArtifactIds": {
      "type": "array",
      "items": {
        "type": "string",
        "format": "uuid"
      }
    }
  }
}
```

## 7. Secret Declaration Model

Secrets are declared at the workflow level and referenced by key from steps. The workflow definition stores references and intended injection points only.

Example:

```json
{
  "secrets": [
    {
      "key": "deploy_api_token",
      "displayName": "Deployment API token",
      "provider": "external",
      "ref": "vault://platform/staging/deploy-api-token",
      "scope": {
        "environment": "staging",
        "targets": ["api"]
      },
      "requiredBy": ["deploy"],
      "injectAs": {
        "type": "env",
        "name": "DEPLOY_TOKEN"
      },
      "redactionHints": ["deploy-token", "api-token"]
    }
  ]
}
```

Rules:

- `key` is the only value a step may reference.
- `ref` is a secret locator, not a secret value.
- `provider` identifies a future broker integration, for example `aws_secrets_manager`, `ssm_parameter`, `vault`, or `external`.
- `requiredBy` must reference existing step IDs.
- A step may only request secrets declared in the top-level `secrets` array.
- Missing secret declarations are validation errors.
- Unknown secret references are validation errors.
- Raw secret-looking values in `inputs.environment`, `headers`, `body`, or artifact metadata should be rejected by semantic validation where detectable.
- Until a credential broker exists, v2 should allow declarations but runner execution must fail closed if an action requires a secret value that cannot be resolved.

Required future files:

- `apps/api/apps/workflows/secret_validation.py`
- `apps/runner/runner/secrets/base.py`
- `apps/runner/runner/secrets/null_provider.py`
- `apps/runner/runner/secrets/redaction.py`

## 8. Artifact Declaration Model

Artifacts should be declared per step so the runner can collect only expected files and Django can evaluate evidence completeness.

Example:

```json
{
  "id": "deploy",
  "artifacts": [
    {
      "key": "deploy_manifest",
      "name": "deploy-manifest.json",
      "path": "artifacts/deploy-manifest.json",
      "kind": "report",
      "mimeType": "application/json",
      "required": true,
      "maxBytes": 1048576,
      "contentDisposition": "attachment",
      "evidenceRole": "deployment_manifest"
    },
    {
      "key": "command_stdout",
      "name": "stdout.txt",
      "kind": "stdout",
      "required": false,
      "maxBytes": 5242880
    }
  ]
}
```

Rules:

- `key` is stable within a workflow definition.
- `path` is required for file/report artifacts and must be relative to the step workspace.
- `stdout` and `stderr` artifacts do not require `path`.
- `kind` must map to existing or added `Artifact.Kind` values.
- `required=true` means execution cannot be considered evidence-complete if the artifact is missing.
- Artifact paths must reject absolute paths, `..`, symlink escapes, sockets, devices, and directories.
- Artifact upload metadata should include `artifact_declaration_key`, `action_type`, `action_version`, `step_key`, and `dry_run`.

Potential model change:

- Add `Artifact.metadata["declaration_key"]` initially.
- Later, if querying becomes important, add a nullable indexed `Artifact.declaration_key` field.

## 9. Timeout, Retry, and Idempotency Declarations

Defaults may be set at workflow level and overridden per step.

Example:

```json
{
  "defaults": {
    "timeoutSeconds": 300,
    "retry": {
      "maxAttempts": 1,
      "backoffSeconds": 0,
      "retryOn": []
    }
  },
  "steps": [
    {
      "id": "health-check",
      "timeoutSeconds": 30,
      "retry": {
        "maxAttempts": 3,
        "backoffSeconds": 5,
        "retryOn": ["runner_transient", "network_transient", "timeout"]
      },
      "idempotency": {
        "mode": "natural",
        "reason": "GET health check has no target mutation."
      }
    }
  ]
}
```

Idempotency modes:

| Mode | Meaning | Automatic retry |
|---|---|---:|
| `none` | Action may not be safe to repeat | No |
| `natural` | Action is inherently safe to repeat | Yes, within retry policy |
| `keyed` | Action uses an explicit idempotency key | Yes, key required |
| `external` | External system guarantees idempotency | Yes, evidence required |

Validation rules:

- `timeoutSeconds` must be positive and capped by runner-pool maximum.
- `retry.maxAttempts` must be at least 1 and capped.
- `retry.maxAttempts > 1` requires idempotency mode other than `none`.
- `idempotency.mode="keyed"` requires a deterministic `key`.
- Mutating `http_request` methods require `idempotency.mode` of `keyed` or `external`.
- Retried attempts must be visible in execution step metadata, audit events, and artifacts.

## 10. Dry-Run Semantics

Dry-run is an execution mode, not just a workflow annotation.

Proposed public API change:

```json
{
  "workflow_id": "00000000-0000-0000-0000-000000000000",
  "mode": "dry_run"
}
```

Valid modes:

- `live`
- `dry_run`

Action dry-run declaration:

```json
{
  "dryRun": {
    "supported": true,
    "strategy": "native",
    "requiresSecrets": false
  }
}
```

Strategies:

| Strategy | Meaning |
|---|---|
| `native` | The underlying tool has a real dry-run or plan mode. |
| `validate_only` | Runner validates inputs, target reachability, and declarations without mutating targets. |
| `mock` | Runner produces simulated result facts; allowed only for non-production test workflows. |
| `unsupported` | Action cannot run in dry-run mode. |

Rules:

- `dry_run` execution must be stored on the `Execution` record or in `workflow_snapshot.executionMode`.
- Policy context must include `execution_mode`.
- A workflow may run in dry-run only if every step either supports dry-run or is control-plane-only.
- Unsupported dry-run steps fail before runner claim.
- Dry-run artifacts must be marked `dry_run=true`.
- Dry-run must never request live-only secrets unless `requiresSecrets=true` and policy permits it.
- Dry-run results are evidence of validation, not evidence that the live operation occurred.

## 11. Validation Architecture

Validation must happen in layers and fail closed.

Proposed files:

- `apps/api/apps/workflows/validators.py`
- `apps/api/apps/workflows/action_catalog.py`
- `apps/api/apps/workflows/schema_loader.py`
- `apps/api/apps/workflows/migrations/0004_workflow_v2_metadata.py` if metadata fields are added
- `apps/runner/runner/actions/schemas.py`
- `apps/runner/runner/actions/registry.py`

Validation layers:

1. JSON schema validation against `workflow.v2.schema.json`.
2. Action catalog lookup for every `(action.type, action.version)`.
3. Action input validation against the action-specific JSON schema.
4. Semantic validation:
   - unique step IDs;
   - `step.type == step.action.type`;
   - supported risk levels;
   - valid approval timeout;
   - valid secret references;
   - valid artifact declarations;
   - retry requires idempotency;
   - dry-run compatibility;
   - action-specific pilot restrictions.
5. Publish preflight:
   - no unresolved required validation errors;
   - AI-parsed workflows reviewed;
   - runner capability requirements are known;
   - policy preflight does not identify hard blocks for all possible executions.
6. Execution creation validation:
   - workflow is published;
   - schema version supported;
   - requested execution mode valid;
   - required runner capabilities can be scheduled;
   - all dry-run/live constraints satisfied.
7. Runner claim validation:
   - runner Pydantic models parse claimed action snapshots;
   - runner version supports all action contracts;
   - dispatch registry contains every action type/version.
8. Step-start validation:
   - existing ownership and policy gates remain authoritative;
   - policy errors fail closed.

Validation flow:

```text
Manual editor or AI parser
        |
        v
Workflow draft JSON
        |
        v
JSON schema validation
        |
        v
Action catalog and semantic validation
        |
        +--> validation errors stored/displayed; cannot publish
        |
        v
Human review, if required
        |
        v
Publish preflight
        |
        v
Published v2 workflow
        |
        v
Create execution: mode, policy preflight, runner capability preflight
        |
        v
Immutable execution snapshot and materialized steps
        |
        v
Runner claim and typed action dispatch
```

## 12. Versioning Strategy

There are three separate versions.

| Version | Owner | Example | Mutability |
|---|---|---|---|
| Workflow schema version | Platform schema | `workflow.schema.v2` | Immutable after release |
| Action catalog version | Platform action registry | `pilot.v1` | Immutable after release |
| Workflow business version | Existing workflow model | `Workflow.version=3` | New row per version |

Rules:

- `Workflow.definition_schema_version` must equal top-level `definition.schemaVersion`.
- Action contracts are addressed by `(action.type, action.version)`.
- Once a published workflow references an action contract, that action contract must not change behavior incompatibly.
- A new action behavior requires a new `action.version`.
- Runner capabilities should advertise supported action contracts, for example `shell_command:pilot.v1`.
- Execution snapshots include the exact workflow and action contract versions used at creation time.

Recommended version constants:

- `workflow.schema.v1`
- `workflow.schema.v2`
- `pilot.v1` for the first action catalog

## 13. Runner Dispatch Mapping

The runner should dispatch by action type and version, not by free-form command fields.

Proposed runner files:

- `apps/runner/runner/actions/base.py`
- `apps/runner/runner/actions/registry.py`
- `apps/runner/runner/actions/manual_task.py`
- `apps/runner/runner/actions/approval_gate.py`
- `apps/runner/runner/actions/shell_command.py`
- `apps/runner/runner/actions/http_request.py`
- `apps/runner/runner/actions/artifact_assertion.py`

Proposed interface:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

@dataclass(frozen=True)
class ActionExecutionContext:
    execution_id: UUID
    step_id: UUID
    step_key: str
    action_type: str
    action_version: str
    execution_mode: str
    attempt: int
    timeout_seconds: int
    inputs: dict[str, Any]
    secrets: dict[str, str]
    artifact_declarations: list[dict[str, Any]]

@dataclass(frozen=True)
class ActionResult:
    status: str
    started_at: datetime
    finished_at: datetime
    exit_code: int | None
    outputs: dict[str, Any]
    artifacts: list[Any]
    failure_kind: str = ""
    error_message: str = ""
    retryable: bool = False

class ActionHandler(Protocol):
    action_type: str
    action_version: str

    def validate(self, context: ActionExecutionContext) -> None:
        ...

    def execute(self, context: ActionExecutionContext) -> ActionResult:
        ...
```

Dispatch map:

```python
ACTION_HANDLERS = {
    ("manual_task", "pilot.v1"): ManualTaskHandler,
    ("approval_gate", "pilot.v1"): ApprovalGateHandler,
    ("shell_command", "pilot.v1"): ShellCommandHandler,
    ("http_request", "pilot.v1"): HttpRequestHandler,
    ("artifact_assertion", "pilot.v1"): ArtifactAssertionHandler,
}
```

Required API serializer changes:

- `apps/api/apps/executions/internal_serializers.py::InternalExecutionStepSerializer` should include `step_snapshot`.
- For v2, include an explicit `action_snapshot` field derived from `step.step_snapshot["action"]`.
- Preserve existing `command` for v1 compatibility.

Required runner schema changes:

- `apps/runner/runner/schemas.py::ClaimedStep` adds:
  - `step_snapshot: dict[str, Any] = {}`
  - `action_snapshot: ActionSnapshot | None = None`
  - `timeout_seconds: int | None = None`
  - `retry: RetrySpec | None = None`
  - `idempotency: IdempotencySpec | None = None`
  - `artifacts: list[ArtifactDeclaration] = []`

Dispatch flow:

```text
Runner receives ClaimedStep
        |
        v
If v1: route through compatibility handler
If v2: parse action_snapshot
        |
        v
Lookup (action.type, action.version)
        |
        +--> missing handler: call step-start only if needed, then fail step with unsupported_action
        |
        v
Call Django step-start gate
        |
        +--> wait_for_approval: poll approval status
        +--> blocked: fail execution path
        |
        v
Resolve secrets and build ActionExecutionContext
        |
        v
handler.validate()
        |
        v
handler.execute()
        |
        v
Upload declared artifacts
        |
        v
Report terminal step status and output facts
```

## 14. Policy Integration Expectations

Existing policy evaluation must remain in Django's step-start path. v2 should enrich policy context rather than moving decisions to the runner.

Current policy condition types:

- `risk_level`
- `step_type`
- `time_window`

Expected v2 policy context additions:

```json
{
  "schema_version": "workflow.schema.v2",
  "catalog_version": "pilot.v1",
  "execution_mode": "live",
  "action_type": "shell_command",
  "action_version": "pilot.v1",
  "risk_level": "high",
  "requires_approval": true,
  "timeout_seconds": 600,
  "retry_max_attempts": 1,
  "idempotency_mode": "none",
  "declared_secret_keys": ["deploy_api_token"],
  "declared_artifact_keys": ["deploy_manifest"],
  "mutates_target": true,
  "dry_run_supported": true
}
```

Potential new policy rule condition types:

- `action_type`
- `action_version`
- `execution_mode`
- `idempotency_mode`
- `secret_scope`
- `artifact_kind`
- `mutates_target`
- `runner_capability`

Policy rules:

- High-risk live `shell_command` should require approval by default.
- Mutating `http_request` should require approval and idempotency.
- Steps declaring production-scoped secrets should require approval.
- Dry-run execution can be auto-approved only if every action supports dry-run and no live-only secret is requested.
- Policy evaluation errors remain fail-closed.

## 15. Audit and Evidence Implications

Audit events must record what was intended and what happened without leaking secrets.

Workflow audit metadata should include:

- `definition_schema_version`
- `catalog_version`
- `definition_hash_sha256`
- `action_types`
- `action_versions`
- `declared_secret_keys`
- `declared_artifact_keys`
- `validation_status`
- `parse_source`
- `requires_review`

Execution audit metadata should include:

- `execution_mode`
- `workflow_snapshot_hash_sha256`
- `runner_capability_match`
- `schema_version`
- `catalog_version`

Step audit metadata should include:

- `action_type`
- `action_version`
- `timeout_seconds`
- `retry_attempt`
- `retry_max_attempts`
- `idempotency_mode`
- `idempotency_key_sha256` when present
- `dry_run`
- `failure_kind`
- declared artifact keys
- declared secret keys, never values

Evidence bundles should include:

- workflow snapshot;
- validation report snapshot;
- action catalog version;
- action contract identifiers;
- policy evaluations;
- approval requests and decisions;
- runner timing facts;
- action output facts;
- artifact declarations;
- uploaded artifact records and checksums;
- evidence completeness result.

## 16. AI Parsing Integration Expectations

AI parsing remains advisory. Django validates and persists.

Required AI changes:

- AI parse output should target v2 candidate shape once v2 authoring is enabled.
- AI should only emit supported pilot action types.
- If the runbook implies unsupported actions, AI should emit `manual_task` plus warnings rather than inventing executable action contracts.
- AI should identify likely secrets as declarations with unresolved refs, not values.
- AI should identify likely artifacts and verification checks.
- AI should emit confidence and warnings per step.
- AI-parsed v2 workflows must set `requires_review=True`.
- Human review remains mandatory before publish.

Proposed AI candidate contract:

```json
{
  "request_id": "parse-123",
  "schemaVersion": "workflow.schema.v2",
  "workflow": {
    "name": "Deploy service",
    "catalogVersion": "pilot.v1",
    "secrets": [],
    "steps": []
  },
  "warnings": [
    {
      "code": "unsupported_action_lifted_to_manual_task",
      "step_id": "db-migrate",
      "detail": "Database migration action is not in the pilot catalog."
    }
  ],
  "confidence": 0.72
}
```

AI integration files likely affected later:

- `apps/ai/app/schemas/workflow_parse.py`
- `apps/ai/app/services/workflow_parser.py`
- `apps/ai/app/prompts/parse.py`
- `apps/ai/app/prompts/enrich.py`
- `apps/api/apps/workflows/internal_clients.py`
- `apps/api/apps/workflows/services.py`

## 17. Migration Strategy From v1

Migration should be opt-in and create new drafts.

Lift rules:

| v1 shape | v2 result |
|---|---|
| `type=manual_task` | `manual_task` action |
| `type=approval` | `approval_gate` action |
| `type=shell_command` with `command` | `shell_command` action with `commandMode="shell"` |
| `requiresApproval=true` | Preserve `requiresApproval=true` |
| `approvalTimeoutSeconds` | Preserve as step approval timeout |
| `risk` | Preserve risk |
| No artifacts | Empty artifact declarations |
| No secrets | Empty secret declarations |
| No retry/idempotency | `retry.maxAttempts=1`, `idempotency.mode="none"` |

Migration service contract:

```python
def create_v2_draft_from_v1(
    *,
    workflow: Workflow,
    actor: AuditActor | None = None,
) -> Workflow:
    """Create a new draft workflow version with a lifted v2 definition."""
```

Rules:

- Only `draft`, `published`, and `superseded` v1 workflows can be lifted.
- The original workflow row is unchanged.
- The migrated workflow starts as `draft`.
- If the source workflow came from AI or the lift introduces shell mode, mark `requires_review=True`.
- The migration result includes a validation report.
- The UI must show a v1-to-v2 diff before publish.

## 18. Required API, Model, and Schema Changes

Schema files:

- Add `packages/workflow-schema/workflow.v2.schema.json`.
- Add action schemas under `packages/workflow-schema/actions/`.
- Add `packages/workflow-schema/action-catalog.pilot.v1.json`.
- Mirror contracts under `packages/contracts/workflow/` if external consumers rely on that package.

Django workflow changes:

- `apps/api/apps/workflows/services.py`
  - branch validation by schema version;
  - materialize v2 validation reports;
  - add v1-to-v2 lift service;
  - enforce v2 publish preflight.
- `apps/api/apps/workflows/validators.py`
  - new v2 structural and semantic validators.
- `apps/api/apps/workflows/action_catalog.py`
  - load and expose supported action contracts.
- `apps/api/apps/workflows/serializers.py`
  - expose validation status/report if persisted.
- `apps/api/apps/workflows/views.py`
  - add validate endpoint and optional migrate endpoint.

Potential model fields:

```python
class Workflow(BaseModel):
    definition_hash_sha256 = models.CharField(max_length=64, blank=True)
    catalog_version = models.CharField(max_length=64, blank=True)
    validation_status = models.CharField(max_length=32, default="unknown")
    validation_report = models.JSONField(default=dict)
```

Django execution changes:

- `apps/api/apps/executions/models.py`
  - add optional `execution_mode`, default `live`;
  - optionally add `workflow_snapshot_hash_sha256`.
- `apps/api/apps/executions/services.py`
  - validate v2 at execution creation;
  - materialize `ExecutionStep` denormalized fields from v2 action steps;
  - copy action info into `step_snapshot`;
  - enforce dry-run compatibility.
- `apps/api/apps/executions/internal_serializers.py`
  - include `step_snapshot` and `action_snapshot`.
- `apps/api/apps/executions/internal_views.py`
  - add action context to policy response metadata where useful.

Runner changes:

- `apps/runner/runner/schemas.py`
  - add v2 action snapshot models.
- `apps/runner/runner/executor.py`
  - dispatch through action handlers.
- `apps/runner/runner/actions/`
  - add action registry and pilot handlers.
- `apps/runner/runner/artifact_uploader.py`
  - support declared file artifact upload in addition to stdout/stderr.
- `apps/runner/runner/sandbox.py`
  - consumed by `shell_command` action handler after Phase A.

## 19. Required Frontend and Editor Changes

The UI must stop treating steps as generic text rows for v2 workflows.

Required frontend changes:

- `apps/web/src/features/workflows/types.ts`
  - add v2 workflow, action, secret, artifact, retry, idempotency, dry-run types.
- `apps/web/src/features/workflows/api/workflowsApi.ts`
  - support validate and migrate endpoints.
- `apps/web/src/routes/workflows/WorkflowDetailPage.tsx`
  - show schema version, catalog version, action types, and validation status.
- `apps/web/src/routes/workflows/WorkflowReviewPage.tsx`
  - render action-specific review summaries for AI-generated v2 workflows.
- New editor components:
  - action type selector;
  - action input form by action type;
  - secret declaration/reference picker;
  - artifact declaration editor;
  - timeout/retry/idempotency controls;
  - dry-run capability display;
  - validation results panel;
  - v1-to-v2 migration diff.

Editor rules:

- Users cannot edit raw JSON as the only authoring path for v2.
- The UI must show raw JSON in a read-only advanced panel for auditability.
- Unsupported action types cannot be saved.
- Secret values must never be entered into the workflow editor.
- Artifact paths should be validated client-side and server-side.
- The "Create execution" action should offer `dry_run` only when server validation says it is supported.

## 20. Test Strategy

Backend tests:

- v2 schema accepts valid pilot workflows.
- v2 schema rejects missing `schemaVersion`, missing `action`, unknown action type, and action type mismatch.
- Semantic validator rejects duplicate step IDs, unknown secret refs, unknown artifact refs, unsafe artifact paths, retry without idempotency, and dry-run unsupported steps.
- Publish rejects invalid v2 workflows.
- Execution creation rejects unknown schema versions.
- Execution creation materializes v2 steps correctly into `ExecutionStep` rows.
- Execution snapshot preserves exact v2 definition.
- v1 execution behavior remains unchanged.
- v1-to-v2 migration creates a new draft and does not mutate source workflow.
- Policy evaluation context includes v2 action facts.
- Audit events include v2 metadata without secret values.

Runner tests:

- `ClaimedStep` parses v1 and v2 payloads.
- Unknown action handler fails closed.
- Unsupported action version fails closed.
- `shell_command` handler builds a sandbox spec from action inputs.
- `http_request` handler enforces method, URL, timeout, response cap, and dry-run rules.
- Declared artifacts are uploaded with declaration metadata.
- Required missing artifacts fail the step.
- Retry executes only when idempotency permits it.
- Dry-run mode avoids live-only action execution.

Frontend tests:

- v2 workflow detail renders action type, version, validation status, secrets, and artifacts.
- editor action forms produce expected payloads;
- validation errors are visible and block publish;
- v1-to-v2 migration diff is visible;
- dry-run button is hidden or disabled when unsupported.

Contract tests:

- Django and runner fixtures share the same v2 workflow examples.
- Action catalog JSON fixtures validate against action schema files.
- A claimed v2 execution fixture round-trips through `apps/runner/runner/schemas.py`.

Suggested fixture files:

- `packages/workflow-schema/examples/workflow-v2-shell-command.valid.json`
- `packages/workflow-schema/examples/workflow-v2-http-request.valid.json`
- `packages/workflow-schema/examples/workflow-v2-invalid-secret-ref.json`
- `apps/api/apps/workflows/tests/fixtures/workflow_v2.py`
- `apps/runner/runner/tests/fixtures/claimed_execution_v2.py`

## 21. Failure Semantics

Failure semantics must be explicit and user-visible.

Validation failures:

- Draft save may persist invalid work-in-progress only if validation status is stored as invalid and publish remains blocked.
- Publish must reject invalid v2 definitions.
- Execution creation must reject invalid or unsupported v2 definitions.

Runner capability failures:

- If no runner can support all action contracts, execution creation should fail or remain queued with an explicit scheduling error, depending on runner-pool design.
- If a runner claims an action it cannot support, it must fail the step with `unsupported_action_contract`; this should be treated as platform failure, not target failure.

Action failures:

- Action input validation failure: step failed, failure kind `action_input_invalid`.
- Secret resolution failure: step failed, failure kind `secret_unavailable`.
- Sandbox setup failure: step failed, failure kind `sandbox_setup_failed`.
- Timeout: step failed, failure kind `timeout`.
- Non-zero command exit: step failed, failure kind `action_failed`.
- HTTP unexpected status: step failed, failure kind `assertion_failed` or `http_status_unexpected`.
- Required artifact missing: step failed, failure kind `required_artifact_missing`.
- Artifact upload rejected: step failed only when artifact is required; otherwise warning metadata.
- Policy block: step failed through existing step-start path, failure kind `policy_blocked`.
- Approval timeout/rejection: existing approval failure path.

Retry failures:

- Retry attempts must be recorded.
- Retry exhaustion marks the step failed with the last failure kind and a retry summary.
- Non-idempotent actions must not be automatically retried.

Execution failure:

- Sequential execution stops on first failed step unless a future explicit `onFailure` policy says otherwise.
- The initial v2 pilot should not support continue-on-error.

## 22. Explicit Non-Goals

This blueprint does not implement code.

Out of scope for Pilot Phase B:

- Building a full hostile-code sandbox.
- Storing or brokering real secret values.
- Adding Terraform, Kubernetes, database, or cloud-provider action types.
- Adding runner pools, target scheduling, or enterprise credential federation.
- Replacing Django policy evaluation with runner-side policy.
- Allowing AI-generated workflows to auto-publish or auto-execute.
- Migrating existing v1 workflows automatically.
- Rewriting historical execution snapshots.
- Adding a queue/broker service.
- Building a complete visual workflow designer.
- Supporting arbitrary third-party action plugins.
- Supporting parallel step graphs or conditional branching.

## 23. Phased Rollout Plan

Phase B.1: Schema and catalog foundations

- Add v2 schema files and action catalog files.
- Add Django schema loader and v2 validators.
- Add valid/invalid schema fixtures.
- No runtime execution changes yet.

Phase B.2: API persistence and validation

- Add validation status/report support.
- Add validate endpoint.
- Enforce v2 validation at publish.
- Keep v1 path unchanged.

Phase B.3: Execution materialization

- Materialize v2 action steps into `ExecutionStep`.
- Include `step_snapshot` and `action_snapshot` in runner claim payload.
- Add execution mode support for `live` and `dry_run`.

Phase B.4: Runner typed dispatch

- Add action handler registry.
- Add v1 compatibility handler.
- Add pilot handlers for `manual_task`, `approval_gate`, `shell_command`, `http_request`, and `artifact_assertion`.
- Wire `shell_command` to Phase A sandbox provider.

Phase B.5: Policy, audit, and evidence enrichment

- Add v2 action facts to policy context.
- Add audit metadata for schema/action versions, dry-run, retries, idempotency, and artifact declarations.
- Add evidence completeness calculation for declared artifacts.

Phase B.6: Frontend editor and migration

- Add v2 read/review UI.
- Add v2 action editor controls.
- Add v1-to-v2 draft migration endpoint and UI.
- Add dry-run execution controls.

Phase B.7: Pilot hardening

- Run end-to-end dry-run and live pilot workflows.
- Verify old v1 workflows still run.
- Verify unknown actions fail closed.
- Verify audit and artifacts are sufficient for review.
- Document operational limitations.

## 24. Acceptance Criteria

Schema and validation:

- `workflow.schema.v2` exists and validates the v2 envelope.
- Action-specific schemas exist for all pilot action types.
- Django rejects unknown schema versions, unknown action types, unknown action versions, action type mismatches, unsafe artifact paths, unknown secret refs, retry without idempotency, and unsupported dry-run requests.
- Existing v1 workflow tests continue to pass.

Execution:

- Published v2 workflows can create immutable execution snapshots.
- `ExecutionStep.step_snapshot` contains the exact v2 step.
- Runner claim payload includes enough action data to dispatch without reading workflow JSON heuristically.
- Unknown runner action contracts fail closed with clear failure kind.
- `shell_command` dispatch uses the sandbox provider, not the old simulated sleep path.

Policy and audit:

- Step-start policy evaluation receives v2 action context.
- Audit events include schema version, action type, action version, dry-run mode, retry attempt, idempotency mode, declared artifact keys, and declared secret keys.
- No raw secret values appear in persisted workflow definitions, execution snapshots, audit metadata, policy context, runner logs, or artifact metadata.

Artifacts and evidence:

- Declared stdout/stderr and file artifacts are uploaded through Django.
- Required missing artifacts fail the step or mark evidence incomplete according to the declared semantics.
- Artifact metadata includes declaration keys and action contract identifiers.

Frontend:

- Workflow detail and review pages display v2 action contracts, validation status, secrets, artifacts, retry, idempotency, and dry-run support.
- Publish is blocked in the UI when server validation reports blocking errors.
- v1-to-v2 migration creates a new draft and shows a diff before publish.

Rollout:

- v2 can be enabled behind a feature flag for selected organizations.
- v1 remains the default until v2 pilot validation is complete.
- A rollback plan exists: disable v2 creation while continuing to run already-created v1 workflows.
