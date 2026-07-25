from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()


@extend_schema(responses=HealthResponseSerializer)
@api_view(["GET"])
def health(request):
    return Response({"status": "ok", "service": "dmquote-back"})
