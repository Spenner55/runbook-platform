from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.common.org_context import ORG_CONTEXT_HEADER
from apps.organizations.models import Membership
from apps.users.models import User


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    memberships = serializers.SerializerMethodField()
    active_organization_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "is_staff",
            "created_at",
            "memberships",
            "active_organization_id",
        )
        read_only_fields = fields

    def get_memberships(self, obj):
        memberships = (
            Membership.objects.select_related("organization")
            .filter(user=obj)
            .order_by("organization__name", "organization__id")
        )
        return [
            {
                "id": str(membership.id),
                "role": membership.role,
                "organization": {
                    "id": str(membership.organization_id),
                    "name": membership.organization.name,
                    "slug": membership.organization.slug,
                },
            }
            for membership in memberships
        ]

    def get_active_organization_id(self, obj):
        request = self.context.get("request")
        requested_org_id = None
        if request is not None:
            requested_org_id = request.headers.get(ORG_CONTEXT_HEADER)
        memberships = self.get_memberships(obj)
        if requested_org_id and any(
            membership["organization"]["id"] == requested_org_id
            for membership in memberships
        ):
            return requested_org_id
        if memberships:
            return memberships[0]["organization"]["id"]
        return None


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(max_length=150, required=False, default="")
    last_name = serializers.CharField(max_length=150, required=False, default="")

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_password(self, value):
        validate_password(value)
        return value
