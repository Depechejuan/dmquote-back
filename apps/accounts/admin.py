from django.contrib import admin
from rest_framework.authtoken.models import Token


@admin.register(Token)
class AccessTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("key", "user", "created")
