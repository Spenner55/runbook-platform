import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.audit.admin import AuditEventAdmin
from apps.audit.models import AuditEvent


@pytest.mark.django_db
def test_audit_admin_is_read_only():
    admin = AuditEventAdmin(AuditEvent, AdminSite())
    request = RequestFactory().get("/admin/audit/auditevent/")

    assert admin.has_add_permission(request) is False
    assert admin.has_delete_permission(request) is False
    assert set(admin.get_readonly_fields(request)) >= {
        "id",
        "actor_type",
        "event_type",
        "object_type",
        "metadata",
        "occurred_at",
    }

    with pytest.raises(PermissionDenied):
        admin.save_model(request, AuditEvent(), form=None, change=True)
