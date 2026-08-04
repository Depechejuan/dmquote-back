from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_album_is_compilation"),
    ]

    operations = [
        migrations.AddField(
            model_name="song",
            name="track_number",
            field=models.PositiveSmallIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
