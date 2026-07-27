import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_dmlive_import_requires_a_local_input_file():
    with pytest.raises(CommandError, match="local --input"):
        call_command("ingest_dmlive")
