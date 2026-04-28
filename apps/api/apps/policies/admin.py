from django.contrib import admin

from apps.policies.models import Policy, PolicyEvaluation, PolicyRule


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "organization__name")


@admin.register(PolicyRule)
class PolicyRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "policy", "priority", "condition_type", "outcome", "is_active")
    list_filter = ("is_active", "condition_type", "outcome")
    search_fields = ("name", "policy__name")


@admin.register(PolicyEvaluation)
class PolicyEvaluationAdmin(admin.ModelAdmin):
    list_display = ("id", "step", "outcome", "effective_outcome", "decision_source", "evaluated_at")
    list_filter = ("outcome", "effective_outcome", "decision_source")

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
