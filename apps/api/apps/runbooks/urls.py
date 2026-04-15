from rest_framework.routers import DefaultRouter

from apps.runbooks.views import RunbookViewSet

router = DefaultRouter()
router.register(r"runbooks", RunbookViewSet, basename="runbook")

urlpatterns = router.urls
