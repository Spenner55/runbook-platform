from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import actor_from_request
from apps.integrations.models import (
    IntegrationConnection,
    IntegrationDeliveryAttempt,
)
from apps.integrations.serializers import (
    IntegrationConnectionCreateSerializer,
    IntegrationConnectionSerializer,
    IntegrationConnectionUpdateSerializer,
    IntegrationDeactivateSerializer,
    IntegrationDeliveryAttemptSerializer,
)
from apps.integrations.services import IntegrationService
from apps.organizations.models import Organization


def _organization_id_from_request(request):
    organization_id = request.query_params.get("organization_id")
    if not organization_id:
        raise ValidationError(
            {
                "organization_id": [
                    "organization_id is required.",
                ]
            },
            code="invalid_query_params",
        )
    return organization_id


def _connection_queryset():
    return IntegrationConnection.objects.select_related("organization").order_by(
        "created_at", "id"
    )


def _connection_for_request(request, integration_id):
    organization_id = _organization_id_from_request(request)
    return get_object_or_404(
        _connection_queryset(),
        pk=integration_id,
        organization_id=organization_id,
    )


def _raise_drf_validation_error(exc: DjangoValidationError):
    if hasattr(exc, "message_dict"):
        raise ValidationError(exc.message_dict)
    raise ValidationError(exc.messages)


def _normalise_optional_json_inputs(data, *, include_defaults=False):
    if hasattr(data, "lists"):
        normalised = {
            key: values[0] if len(values) == 1 else values
            for key, values in data.lists()
        }
    else:
        normalised = dict(data)
    if normalised.get("config") == "":
        normalised["config"] = {}
    if include_defaults and "config" not in normalised:
        normalised["config"] = {}
    if normalised.get("event_types") == "":
        normalised["event_types"] = []
    if include_defaults and "event_types" not in normalised:
        normalised["event_types"] = []
    return normalised


class IntegrationConnectionListCreateView(APIView):
    def get(self, request):
        organization_id = _organization_id_from_request(request)
        qs = _connection_queryset().filter(organization_id=organization_id)
        return Response(IntegrationConnectionSerializer(qs, many=True).data)

    def post(self, request):
        input_data = _normalise_optional_json_inputs(request.data, include_defaults=True)
        serializer = IntegrationConnectionCreateSerializer(data=input_data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        organization = get_object_or_404(Organization, pk=data["organization_id"])

        try:
            connection = IntegrationService.create_connection(
                organization=organization,
                type=data["type"],
                name=data["name"],
                credentials=data["credentials"],
                config=data.get("config"),
                event_types=input_data.get("event_types"),
                actor=actor_from_request(request),
            )
        except DjangoValidationError as exc:
            _raise_drf_validation_error(exc)

        return Response(
            IntegrationConnectionSerializer(connection).data,
            status=status.HTTP_201_CREATED,
        )


class IntegrationConnectionDetailView(APIView):
    def get(self, request, integration_id):
        connection = _connection_for_request(request, integration_id)
        return Response(IntegrationConnectionSerializer(connection).data)

    def patch(self, request, integration_id):
        connection = _connection_for_request(request, integration_id)
        input_data = _normalise_optional_json_inputs(request.data)
        serializer = IntegrationConnectionUpdateSerializer(data=input_data)
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        if "event_types" in input_data:
            fields["event_types"] = input_data["event_types"]

        try:
            connection = IntegrationService.update_connection(
                connection=connection,
                actor=actor_from_request(request),
                **fields,
            )
        except DjangoValidationError as exc:
            _raise_drf_validation_error(exc)

        return Response(IntegrationConnectionSerializer(connection).data)


class IntegrationDeactivateView(APIView):
    def post(self, request, integration_id):
        serializer = IntegrationDeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        connection = _connection_for_request(request, integration_id)
        connection = IntegrationService.deactivate_connection(
            connection=connection,
            actor=actor_from_request(request),
        )
        return Response(IntegrationConnectionSerializer(connection).data)


class IntegrationDeliveryAttemptListView(APIView):
    def get(self, request, integration_id):
        connection = _connection_for_request(request, integration_id)
        qs = IntegrationDeliveryAttempt.objects.filter(
            integration=connection,
            organization_id=connection.organization_id,
        ).order_by("-attempted_at", "-created_at")
        return Response(
            {"results": IntegrationDeliveryAttemptSerializer(qs, many=True).data}
        )
