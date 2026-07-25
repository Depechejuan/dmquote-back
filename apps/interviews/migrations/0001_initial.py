from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("catalog", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Interview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("slug", models.SlugField(max_length=280, unique=True)),
                ("date_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("date_month", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("date_day", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("date_precision", models.CharField(choices=[("day", "Day"), ("month", "Month"), ("year", "Year"), ("unknown", "Unknown")], default="unknown", max_length=12)),
                ("outlet", models.CharField(blank=True, max_length=255)),
                ("location", models.CharField(blank=True, max_length=255)),
                ("source_url", models.URLField(max_length=500)),
                ("audio_url", models.URLField(blank=True, max_length=500)),
                ("transcript_status", models.CharField(choices=[("missing", "Missing"), ("partial", "Partial"), ("complete", "Complete"), ("needs_review", "Needs review")], default="missing", max_length=20)),
                ("publication_status", models.CharField(choices=[("metadata_only", "Metadata only"), ("authorized_text", "Authorized text"), ("pending_permission", "Pending permission"), ("private_only", "Private only")], default="metadata_only", max_length=24)),
                ("notes", models.TextField(blank=True)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-date_year", "-date_month", "-date_day", "title"], "indexes": [models.Index(fields=["date_year", "transcript_status"], name="interview_date_status_idx"), models.Index(fields=["publication_status"], name="interview_publication_idx")]},
        ),
        migrations.CreateModel(
            name="InterviewParticipant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(blank=True, max_length=120)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("interview", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="participant_links", to="interviews.interview")),
                ("person", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="interview_links", to="catalog.person")),
            ],
            options={"ordering": ["sort_order", "person__name"], "constraints": [models.UniqueConstraint(fields=("interview", "person"), name="unique_interview_participant")]},
        ),
        migrations.CreateModel(
            name="SourceSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_url", models.URLField(max_length=500)),
                ("retrieved_at", models.DateTimeField(auto_now_add=True)),
                ("http_status", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("etag", models.CharField(blank=True, max_length=255)),
                ("last_modified", models.CharField(blank=True, max_length=255)),
                ("content_hash", models.CharField(blank=True, max_length=128)),
                ("status", models.CharField(choices=[("success", "Success"), ("not_modified", "Not modified"), ("error", "Error"), ("blocked", "Blocked")], max_length=20)),
                ("error_message", models.TextField(blank=True)),
                ("interview", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="source_snapshots", to="interviews.interview")),
            ],
            options={"ordering": ["-retrieved_at"]},
        ),
    ]
