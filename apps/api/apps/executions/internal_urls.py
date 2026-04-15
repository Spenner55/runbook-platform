from django.urls import path

from apps.executions.views import claim_next, complete, heartbeat, step_update

urlpatterns = [
    path("executions/claim-next/", claim_next, name="internal-claim-next"),
    path("executions/<uuid:execution_id>/heartbeat/", heartbeat, name="internal-heartbeat"),
    path(
        "executions/<uuid:execution_id>/steps/<uuid:step_id>/update/",
        step_update,
        name="internal-step-update",
    ),
    path("executions/<uuid:execution_id>/complete/", complete, name="internal-complete"),
]
