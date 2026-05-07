from django.core.exceptions import ValidationError


def assert_bundle_mutable(bundle) -> None:
    if bundle.is_sealed:
        raise ValidationError(
            "Sealed evidence bundles are immutable.",
            code="evidence_bundle_immutable",
        )
