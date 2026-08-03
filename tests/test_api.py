import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from rest_framework.test import APIClient

from apps.catalog.models import Album, Song


def test_root_returns_ok():
    response = Client().get("/")

    assert response.status_code == 200
    assert response.content == b"ok"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/interviews/",
        "/api/v1/songs/",
        "/api/v1/albums/",
        "/api/v1/transcription-needed/",
    ],
)
def test_empty_catalogue_endpoints_are_public(path):
    response = APIClient().get(path)
    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.django_db
def test_music_catalog_groups_and_orders_albums_and_standalone_songs():
    late_album = Album.objects.create(title="Zeta", slug="zeta", release_year=1990)
    Album.objects.create(title="Alpha", slug="alpha", release_year=1981)
    Song.objects.create(title="Second", slug="second", album=late_album)
    Song.objects.create(title="First", slug="first", album=late_album)
    Song.objects.create(title="Unattached", slug="unattached")

    response = APIClient().get("/api/v1/music/")

    assert response.status_code == 200
    payload = response.json()
    assert [album["title"] for album in payload["albums"]] == ["Alpha", "Zeta"]
    assert [song["title"] for song in payload["albums"][1]["songs"]] == [
        "First",
        "Second",
    ]
    assert [song["title"] for song in payload["standalone_songs"]] == ["Unattached"]
    assert all(
        set(song) == {"id", "title", "slug"}
        for album in payload["albums"]
        for song in album["songs"]
    )


def test_production_frontend_origin_is_allowed_for_api_requests():
    assert "https://dmquote.netlify.app" in settings.CORS_ALLOWED_ORIGINS
    response = APIClient().get(
        "/api/v1/health/",
        HTTP_ORIGIN="https://dmquote.netlify.app",
    )

    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == "https://dmquote.netlify.app"


@pytest.mark.django_db
@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
def test_admin_login_accepts_a_fresh_csrf_token():
    get_user_model().objects.create_superuser(
        username="csrf-admin",
        email="csrf-admin@example.test",
        password="safe-test-password",
    )
    client = Client(enforce_csrf_checks=True)
    login_page = client.get("/dmlog/login/", HTTP_HOST="localhost")
    token = client.cookies["dmquote_csrftoken"].value

    response = client.post(
        "/dmlog/login/",
        {
            "username": "csrf-admin",
            "password": "safe-test-password",
            "csrfmiddlewaretoken": token,
        },
        HTTP_HOST="localhost",
    )

    assert login_page.status_code == 200
    assert response.status_code == 302
    assert response["Location"] == "/accounts/profile/"
