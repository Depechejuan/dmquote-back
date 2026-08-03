import pytest
from django.core.management import call_command

from apps.interviews.models import Interview, SourceSnapshot
from apps.interviews.source_urls import build_dmlive_url


def test_builds_the_canonical_example_url():
    assert build_dmlive_url("1981-08-23 Twentieth Century Box, ITV, UK") == (
        "https://dmlive.wiki/wiki/1981-08-23_Twentieth_Century_Box,_ITV,_UK"
    )


def test_preserves_valid_path_punctuation_and_encodes_unicode():
    assert build_dmlive_url("2000-04-12/19 A & B (Live), München") == (
        "https://dmlive.wiki/wiki/2000-04-12/19_A_&_B_(Live),_M%C3%BCnchen"
    )


def test_adds_a_section_anchor_without_encoding_the_fragment_separator():
    assert build_dmlive_url("Interview title", "interview-transcript") == (
        "https://dmlive.wiki/wiki/Interview_title#interview-transcript"
    )


@pytest.mark.django_db
def test_repair_command_updates_interviews_and_snapshots_idempotently(capsys):
    interview = Interview.objects.create(
        title="1981-08-23 Twentieth Century Box, ITV, UK",
        slug="1981-08-23-twentieth-century-box-itv-uk",
        source_url="https://dmlive.wiki/wiki/old-title",
        source_page_id=123,
    )
    SourceSnapshot.objects.create(
        interview=interview,
        source_url="https://dmlive.wiki/wiki/old-title",
        source_page_id=123,
        status=SourceSnapshot.Status.SUCCESS,
    )

    call_command("repair_dmlive_urls")
    interview.refresh_from_db()
    snapshot = interview.source_snapshots.get()
    expected = "https://dmlive.wiki/wiki/1981-08-23_Twentieth_Century_Box,_ITV,_UK"
    assert interview.source_url == expected
    assert snapshot.source_url == expected
    assert '"interviews_changed": 1' in capsys.readouterr().out

    call_command("repair_dmlive_urls")
    assert '"interviews_changed": 0' in capsys.readouterr().out
