class _BaseDomainError(Exception):
    def __init__(self, *, code: str, detail: str, attr: str | None = None):
        self.code = code
        self.detail = detail
        self.attr = attr
        super().__init__(detail)


class DomainValidationError(_BaseDomainError):
    """A business rule was violated on a single field or object."""
    http_status = 400


class DomainConflictError(_BaseDomainError):
    """A uniqueness invariant was violated (e.g. duplicate slug within org)."""
    http_status = 409


class ConcurrencyConflictError(_BaseDomainError):
    """A concurrent write caused a version or state conflict."""
    http_status = 409


class InvalidWorkflowDefinitionError(_BaseDomainError):
    """A workflow definition failed structural validation."""
    http_status = 400


class ExternalDependencyError(_BaseDomainError):
    """An internal dependency (e.g. AI service) could not be reached or returned an unusable response."""
    http_status = 503


class InvalidStateTransitionError(_BaseDomainError):
    """An operation was rejected because the resource is in an incompatible lifecycle state."""
    http_status = 409
