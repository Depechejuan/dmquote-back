import pytest
from rest_framework.test import APIClient


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
