import pytest

from apps.users import services
from apps.users.models import User


@pytest.mark.django_db
def test_create_user_service():
    user = services.create_user(email="alice@example.com", password="s3cr3tpass!")
    assert isinstance(user, User)
    assert user.email == "alice@example.com"


@pytest.mark.django_db
def test_create_user_normalises_email():
    user = services.create_user(email="Alice@EXAMPLE.COM", password="s3cr3tpass!")
    assert user.email == "alice@example.com"


@pytest.mark.django_db
def test_authenticate_user_success():
    services.create_user(email="bob@example.com", password="pass123!")
    user = services.authenticate_user(email="bob@example.com", password="pass123!")
    assert user.email == "bob@example.com"


@pytest.mark.django_db
def test_authenticate_user_bad_password():
    services.create_user(email="carol@example.com", password="correct!")
    with pytest.raises(services.AuthenticationError):
        services.authenticate_user(email="carol@example.com", password="wrong!")


@pytest.mark.django_db
def test_authenticate_user_inactive():
    user = services.create_user(email="inactive@example.com", password="pass123!")
    user.is_active = False
    user.save()
    with pytest.raises(services.AuthenticationError):
        services.authenticate_user(email="inactive@example.com", password="pass123!")
