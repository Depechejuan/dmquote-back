from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [("interviews", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Transcript",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("language", models.CharField(default="en", max_length=12)),
                ("status", models.CharField(choices=[("missing", "Missing"), ("partial", "Partial"), ("complete", "Complete"), ("needs_review", "Needs review")], default="missing", max_length=20)),
                ("publication_status", models.CharField(choices=[("metadata_only", "Metadata only"), ("authorized_text", "Authorized text"), ("pending_permission", "Pending permission"), ("private_only", "Private only")], default="private_only", max_length=24)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("interview", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="transcript", to="interviews.interview")),
            ],
        ),
        migrations.CreateModel(
            name="TranscriptParagraph",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveIntegerField()),
                ("speaker", models.CharField(blank=True, max_length=160)),
                ("text", models.TextField()),
                ("start_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("end_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("publication_status", models.CharField(choices=[("metadata_only", "Metadata only"), ("authorized_text", "Authorized text"), ("pending_permission", "Pending permission"), ("private_only", "Private only")], default="private_only", max_length=24)),
                ("transcript", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="paragraphs", to="transcripts.transcript")),
            ],
            options={"ordering": ["order"], "constraints": [models.UniqueConstraint(fields=("transcript", "order"), name="unique_transcript_paragraph_order")]},
        ),
    ]
