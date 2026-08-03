import pytest
from django.conf import settings
from django.test import Client
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
