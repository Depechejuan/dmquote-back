import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_ensure_superuser_creates_configured_user(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "depechejuan")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "test-password")
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "juan@example.test")

    call_command("ensure_superuser")

    user = get_user_model().objects.get(username="depechejuan")
    assert user.is_active
    assert user.is_staff
    assert user.is_superuser
    assert user.check_password("test-password")


@pytest.mark.django_db
def test_ensure_superuser_is_idempotent(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "depechejuan")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "test-password")

    call_command("ensure_superuser")
    call_command("ensure_superuser")

    assert get_user_model().objects.filter(username="depechejuan").count() == 1


@pytest.mark.django_db
def test_ensure_superuser_requires_credentials(monkeypatch):
    monkeypatch.delenv("DJANGO_SUPERUSER_USERNAME", raising=False)
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)

    with pytest.raises(CommandError, match="must be set"):
        call_command("ensure_superuser")
