from django.contrib import admin

from apps.approvals.models import ApprovalDecision, ApprovalRequest


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "status", "execution_id", "requested_by_runner_id", "requested_at", "expires_at"]
    list_filter = ["status"]
    raw_id_fields = ["organization", "execution", "step"]


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(admin.ModelAdmin):
    list_display = ["id", "decision", "source_type", "decided_by_label", "decided_at"]
    list_filter = ["decision", "source_type"]
    raw_id_fields = ["approval_request", "decided_by_user"]
