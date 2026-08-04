from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_song_is_b_side"),
    ]

    operations = [
        migrations.AddField(
            model_name="album",
            name="is_compilation",
            field=models.BooleanField(default=False),
        ),
    ]
