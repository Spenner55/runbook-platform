from uuid import UUID

from apps.common.exceptions import DomainValidationError

ORG_CONTEXT_HEADER = "X-Organization-Id"


def require_organization_id(request) -> str:
    """Return the authenticated organization context from X-Organization-Id."""
    header_value = request.headers.get(ORG_CONTEXT_HEADER)
    if not header_value:
        raise DomainValidationError(
            code="organization_id_required",
            detail="X-Organization-Id header is required.",
            attr=ORG_CONTEXT_HEADER,
        )

    organization_id = _normalize_uuid(
        header_value,
        code="organization_id_invalid",
        detail="X-Organization-Id header must be a UUID.",
        attr=ORG_CONTEXT_HEADER,
    )
    _assert_request_organization_matches_header(request, organization_id)
    return organization_id


def require_matching_organization_id(request, organization_id) -> str:
    """Require the org header and ensure it matches a URL-derived organization id."""
    header_organization_id = require_organization_id(request)
    expected_organization_id = _normalize_uuid(
        organization_id,
        code="organization_id_invalid",
        detail="organization_id must be a UUID.",
        attr="organization_id",
    )
    if header_organization_id != expected_organization_id:
        raise DomainValidationError(
            code="org_id_mismatch",
            detail="X-Organization-Id header and URL organization_id do not match.",
            attr="organization_id",
        )
    return header_organization_id


def _assert_request_organization_matches_header(
    request, header_organization_id: str
) -> None:
    for source, value in _request_organization_ids(request):
        request_organization_id = _normalize_uuid(
            value,
            code="organization_id_invalid",
            detail=f"{source} organization_id must be a UUID.",
            attr="organization_id",
        )
        if request_organization_id != header_organization_id:
            raise DomainValidationError(
                code="org_id_mismatch",
                detail=f"X-Organization-Id header and {source} organization_id do not match.",
                attr="organization_id",
            )


def _request_organization_ids(request):
    query_organization_id = request.query_params.get("organization_id")
    if query_organization_id:
        yield "query", query_organization_id

    data = getattr(request, "data", None)
    if not hasattr(data, "get"):
        return
    body_organization_id = data.get("organization_id")
    if body_organization_id:
        yield "body", body_organization_id


def _normalize_uuid(value, *, code: str, detail: str, attr: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(code=code, detail=detail, attr=attr) from exc
