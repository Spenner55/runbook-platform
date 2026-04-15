from rest_framework.routers import DefaultRouter

from apps.organizations.views import OrganizationViewSet

router = DefaultRouter()
router.register(r"organizations", OrganizationViewSet, basename="organization")

urlpatterns = router.urls
