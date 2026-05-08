# Phase 11.6 Audit Integration Notes

Phase 11.6 auditor mutation actions emit append-only `AuditEvent` rows for external references, service catalog entries, control mapping profiles, control coverage recomputation, and auditor access grants.

Auditor search and detail `GET` access does not emit audit events in this phase. The existing audit model and service are used for append-only domain event records, not high-volume read-access telemetry. Adding read-access events would require a deliberate product and retention decision for event volume, access-log privacy, pagination behavior, and whether every list page, filter change, and detail view should be durable audit history.

