from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("catalog", "0001_initial"),
        ("interviews", "0001_initial"),
        ("transcripts", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="InterviewEntityLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(choices=[("interview", "Interview"), ("paragraph", "Paragraph")], default="interview", max_length=12)),
                ("method", models.CharField(choices=[("manual", "Manual"), ("rules", "Rules"), ("ai", "AI")], default="manual", max_length=10)),
                ("confidence", models.DecimalField(blank=True, decimal_places=4, max_digits=5, null=True)),
                ("review_status", models.CharField(choices=[("suggested", "Suggested"), ("verified", "Verified"), ("rejected", "Rejected")], default="suggested", max_length=12)),
                ("start_offset", models.PositiveIntegerField(blank=True, null=True)),
                ("end_offset", models.PositiveIntegerField(blank=True, null=True)),
                ("evidence", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("album", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="interview_links", to="catalog.album")),
                ("interview", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entity_links", to="interviews.interview")),
                ("paragraph", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="entity_links", to="transcripts.transcriptparagraph")),
                ("song", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="interview_links", to="catalog.song")),
            ],
            options={"ordering": ["interview__date_year", "interview__title"], "constraints": [
                models.CheckConstraint(condition=models.Q(models.Q(("song__isnull", False), ("album__isnull", True)), models.Q(("song__isnull", True), ("album__isnull", False)), _connector="OR"), name="link_targets_exactly_one_entity"),
                models.CheckConstraint(condition=(models.Q(scope="interview", paragraph__isnull=True) | models.Q(scope="paragraph", paragraph__isnull=False)), name="link_scope_matches_paragraph"),
            ]},
        ),
    ]
