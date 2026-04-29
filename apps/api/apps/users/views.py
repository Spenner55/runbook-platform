from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users import services
from apps.users.serializers import LoginSerializer, UserSerializer

REFRESH_COOKIE = "refresh_token"
_COOKIE_SECURE = not getattr(settings, "DEBUG", True)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        httponly=True,
        samesite="Strict",
        secure=_COOKIE_SECURE,
        path="/api/v1/auth/",
    )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = services.authenticate_user(
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except services.AuthenticationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        refresh = RefreshToken.for_user(user)
        response = Response(
            {
                "access": str(refresh.access_token),
                "user": UserSerializer(user, context={"request": request}).data,
            }
        )
        _set_refresh_cookie(response, str(refresh))
        return response


class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        raw = request.COOKIES.get(REFRESH_COOKIE)
        if not raw:
            return Response(
                {"detail": "Refresh token missing."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            refresh = RefreshToken(raw)
            access = str(refresh.access_token)
        except (TokenError, InvalidToken) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        response = Response({"access": access})
        # Rotate the refresh cookie if ROTATE_REFRESH_TOKENS is enabled
        if getattr(settings, "SIMPLE_JWT", {}).get("ROTATE_REFRESH_TOKENS", False):
            refresh.blacklist() if hasattr(refresh, "blacklist") else None
            new_refresh = RefreshToken.for_user(refresh.get("user_id"))  # type: ignore[arg-type]
            _set_refresh_cookie(response, str(new_refresh))
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth/")
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user, context={"request": request}).data)
