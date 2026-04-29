from rest_framework import serializers

from apps.organizations.models import Membership, MembershipRole, Organization
from apps.users.models import User


class OrganizationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    slug = serializers.SlugField(max_length=64)


class OrganizationListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "created_at", "updated_at"]


class OrganizationDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "created_at", "updated_at"]


class MembershipUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    user = MembershipUserSerializer(read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    organization_id = serializers.UUIDField(source="organization.id", read_only=True)

    class Meta:
        model = Membership
        fields = [
            "id",
            "organization_id",
            "user_id",
            "user",
            "role",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class MembershipCreateSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(
        choices=MembershipRole.choices, default=MembershipRole.OPERATOR
    )

    def validate_user_id(self, value):
        if not User.objects.filter(pk=value).exists():
            raise serializers.ValidationError("User does not exist.")
        return value


class MembershipRoleUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=MembershipRole.choices)
