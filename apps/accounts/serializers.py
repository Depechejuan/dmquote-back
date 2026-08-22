from rest_framework import serializers


class AccessTokenSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = serializers.CharField()
    is_staff = serializers.BooleanField()


class CurrentUserSerializer(serializers.Serializer):
    is_authenticated = serializers.BooleanField()
    username = serializers.CharField(allow_null=True)
    is_staff = serializers.BooleanField()
