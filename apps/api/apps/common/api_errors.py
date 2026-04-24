from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

from apps.common.exceptions import _BaseDomainError


def _error_envelope(errors: list[dict]) -> dict:
    return {"errors": errors}


def _entry(*, code: str, detail: str, attr: str | None = None) -> dict:
    entry = {"code": code, "detail": detail, "attr": attr}
    return entry


def custom_exception_handler(exc, context):
    # Let DRF build its default response first for its own exceptions.
    response = drf_default_handler(exc, context)

    if response is not None:
        # Normalise DRF's ValidationError detail into our envelope.
        errors = _flatten_drf_errors(response.data)
        response.data = _error_envelope(errors)
        return response

    # Handle our own domain exceptions.
    if isinstance(exc, _BaseDomainError):
        errors = [_entry(code=exc.code, detail=exc.detail, attr=exc.attr)]
        return Response(_error_envelope(errors), status=exc.http_status)

    return None


def _flatten_drf_errors(data) -> list[dict]:
    """Recursively flatten DRF's nested error structure into a flat list."""
    errors: list[dict] = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                errors.append(_entry(code="invalid", detail=item))
            elif hasattr(item, "code"):
                errors.append(_entry(code=item.code or "invalid", detail=str(item)))
            else:
                errors.extend(_flatten_drf_errors(item))
        return errors

    if isinstance(data, dict):
        for field, messages in data.items():
            if field == "non_field_errors":
                attr = None
            else:
                attr = field
            if isinstance(messages, list):
                for msg in messages:
                    if hasattr(msg, "code"):
                        errors.append(
                            _entry(
                                code=msg.code or "invalid", detail=str(msg), attr=attr
                            )
                        )
                    else:
                        errors.append(
                            _entry(code="invalid", detail=str(msg), attr=attr)
                        )
            elif isinstance(messages, str):
                errors.append(_entry(code="invalid", detail=messages, attr=attr))
            else:
                errors.extend(_flatten_drf_errors(messages))
        return errors

    # Scalar fallback.
    detail = str(data)
    code = data.code if hasattr(data, "code") else "invalid"
    errors.append(_entry(code=code, detail=detail))
    return errors
