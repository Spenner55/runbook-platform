from django.contrib.auth import authenticate

from apps.users.models import User


class AuthenticationError(Exception):
    pass


def create_user(*, email: str, password: str, first_name: str = "", last_name: str = "") -> User:
    return User.objects.create_user(
        email=email.lower(),
        password=password,
        first_name=first_name,
        last_name=last_name,
    )


def authenticate_user(*, email: str, password: str) -> User:
    user = authenticate(username=email, password=password)
    if user is None:
        raise AuthenticationError("Invalid credentials.")
    if not user.is_active:
        raise AuthenticationError("Account is disabled.")
    return user
