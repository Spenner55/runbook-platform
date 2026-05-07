from apps.evidence.models import EvidenceBundle, EvidenceExport, LegalHold


def evidence_bundles_for_organization(organization):
    return EvidenceBundle.objects.filter(organization=organization)


def evidence_exports_for_organization(organization):
    return EvidenceExport.objects.filter(organization=organization)


def legal_holds_for_organization(organization):
    return LegalHold.objects.filter(organization=organization)
