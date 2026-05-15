from rest_framework import serializers


class RunnerRegisterRequestSerializer(serializers.Serializer):
    registration_token = serializers.CharField()
    organization_id = serializers.UUIDField(
        required=False, allow_null=True, default=None
    )
    pool_key = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    display_name = serializers.CharField(max_length=255)
    runner_version = serializers.CharField(max_length=64, default="0.1.0")
    fingerprint_sha256 = serializers.CharField(max_length=64, default="")
    hostname = serializers.CharField(max_length=255, default="")
    labels = serializers.DictField(child=serializers.CharField(), default=dict)
    capabilities = serializers.ListField(child=serializers.CharField(), default=list)


class RunnerRegisterResponseSerializer(serializers.Serializer):
    runner_id = serializers.CharField()
    pool_key = serializers.CharField()
    accepted_labels = serializers.DictField()
    accepted_capabilities = serializers.ListField()
    heartbeat_interval_seconds = serializers.IntegerField()
    poll_interval_seconds = serializers.IntegerField()


class RunnerHeartbeatRequestSerializer(serializers.Serializer):
    runner_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    runner_version = serializers.CharField(max_length=64, default="", allow_blank=True)
    hostname = serializers.CharField(max_length=255, default="", allow_blank=True)
    current_execution_count = serializers.IntegerField(default=0, min_value=0)
    observed_pool_key = serializers.CharField(max_length=64, default="", allow_blank=True)
    capabilities_checksum = serializers.CharField(max_length=64, default="", allow_blank=True)
    sent_at = serializers.DateTimeField(required=False, allow_null=True)


class RunnerHeartbeatResponseSerializer(serializers.Serializer):
    runner_id = serializers.CharField()
    status = serializers.CharField()
    last_heartbeat_at = serializers.DateTimeField(allow_null=True)
    runner_action = serializers.ChoiceField(choices=["continue", "drain"])
    poll_interval_seconds = serializers.IntegerField()
