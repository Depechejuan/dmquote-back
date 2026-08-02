import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.interviews.models import Interview
from apps.mentions.models import InterviewEntityLink


@pytest.mark.django_db
def test_audit_report_is_json_and_flags_unreviewed_mentions(capsys):
    interview = Interview.objects.create(
        title="1984 Radio One",
        slug="1984-radio-one",
        source_url="https://dmlive.wiki/wiki/1984_Radio_One",
        source_page_id=10,
    )
    assert interview.source_domain == "dmlive.wiki"

    call_command("audit_dmlive")
    report = json.loads(capsys.readouterr().out)

    assert report["source"]["domain"] == "dmlive.wiki"
    assert report["catalog"]["interviews"] == 1
    assert report["editorial_audit"]["interviews_source_present"] == 1
    assert report["mentions"]["total"] == InterviewEntityLink.objects.count()


@pytest.mark.django_db
def test_authorize_command_requires_confirmation_and_authorizes_text():
    interview = Interview.objects.create(
        title="1984 Radio One",
        slug="1984-radio-one",
        source_url="https://dmlive.wiki/wiki/1984_Radio_One",
        source_page_id=10,
    )

    with pytest.raises(CommandError, match="--confirm"):
        call_command("authorize_dmlive")

    call_command("authorize_dmlive", confirm=True)
    interview.refresh_from_db()
    assert interview.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
