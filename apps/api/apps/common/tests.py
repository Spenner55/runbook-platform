from django.conf import settings
from django.test import TestCase

from apps.common.models import BaseModel


class BaseModelTest(TestCase):
    def test_base_model_is_abstract(self):
        self.assertTrue(BaseModel._meta.abstract)

    def test_base_model_has_expected_fields(self):
        field_names = [f.name for f in BaseModel._meta.fields]
        self.assertIn("id", field_names)
        self.assertIn("created_at", field_names)
        self.assertIn("updated_at", field_names)


def test_default_api_permission_requires_authentication():
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]
