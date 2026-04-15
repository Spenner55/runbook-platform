from rest_framework.routers import DefaultRouter

from apps.workflows.views import WorkflowViewSet

router = DefaultRouter()
router.register(r"workflows", WorkflowViewSet, basename="workflow")

urlpatterns = router.urls
