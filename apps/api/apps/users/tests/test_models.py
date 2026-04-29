import pytest

from apps.users.models import User


@pytest.mark.django_db
def test_create_user():
    user = User.objects.create_user(email="alice@example.com", password="s3cr3tpass!")
    assert user.pk is not None
    assert user.email == "alice@example.com"
    assert user.is_active is True
    assert user.is_staff is False
    assert user.check_password("s3cr3tpass!")


@pytest.mark.django_db
def test_create_superuser():
    user = User.objects.create_superuser(email="admin@example.com", password="adm!npass1")
    assert user.is_staff is True
    assert user.is_superuser is True


@pytest.mark.django_db
def test_email_is_unique():
    User.objects.create_user(email="dup@example.com", password="pass123!")
    with pytest.raises(Exception):
        User.objects.create_user(email="dup@example.com", password="other123!")


@pytest.mark.django_db
def test_full_name():
    user = User.objects.create_user(
        email="bob@example.com", password="pass123!", first_name="Bob", last_name="Smith"
    )
    assert user.full_name == "Bob Smith"


@pytest.mark.django_db
def test_full_name_partial():
    user = User.objects.create_user(email="jane@example.com", password="pass123!", first_name="Jane")
    assert user.full_name == "Jane"
