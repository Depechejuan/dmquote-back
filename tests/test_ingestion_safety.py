import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_dmlive_import_is_opt_in():
    with pytest.raises(CommandError, match="disabled by default"):
        call_command("ingest_dmlive")
