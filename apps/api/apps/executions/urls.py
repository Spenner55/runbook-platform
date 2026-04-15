from rest_framework.routers import DefaultRouter

from apps.executions.views import ExecutionViewSet

router = DefaultRouter()
router.register(r"executions", ExecutionViewSet, basename="execution")

urlpatterns = router.urls
