from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

from .serializers import AccessTokenSerializer, CurrentUserSerializer


@extend_schema(
    responses={200: CurrentUserSerializer},
    description="Return the current Django Admin user, if the request is authenticated.",
)
@api_view(["GET"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([AllowAny])
def current_user(request):
    user = request.user
    if not user.is_authenticated:
        return Response(
            {"is_authenticated": False, "username": None, "is_staff": False}
        )
    return Response(
        {
            "is_authenticated": True,
            "username": user.get_username(),
            "is_staff": user.is_staff,
        }
    )


@extend_schema(
    request=None,
    responses={
        200: AccessTokenSerializer,
        403: OpenApiResponse(description="Django Admin staff access required."),
    },
    description=(
        "Issue or return the DRF token for the user already authenticated through Django Admin. "
        "This endpoint never accepts a password."
    ),
)
@api_view(["POST"])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAdminUser])
def issue_access_token(request):
    token, _ = Token.objects.get_or_create(user=request.user)
    return Response(
        {
            "token": token.key,
            "user": request.user.get_username(),
            "is_staff": request.user.is_staff,
        }
    )
