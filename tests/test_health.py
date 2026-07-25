import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_endpoint():
    response = APIClient().get("/api/v1/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "dmquote-back"}
