from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Album",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160, unique=True)),
                ("slug", models.SlugField(max_length=180, unique=True)),
                ("release_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
            ],
            options={"ordering": ["release_year", "title"]},
        ),
        migrations.CreateModel(
            name="Person",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, unique=True)),
                ("slug", models.SlugField(max_length=180, unique=True)),
                ("role", models.CharField(blank=True, max_length=120)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Song",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160, unique=True)),
                ("slug", models.SlugField(max_length=180, unique=True)),
                ("release_year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("album", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="songs", to="catalog.album")),
            ],
            options={"ordering": ["title"]},
        ),
        migrations.CreateModel(
            name="AlbumAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.CharField(max_length=160)),
                ("normalized_value", models.CharField(db_index=True, max_length=160)),
                ("album", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="aliases", to="catalog.album")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("album", "value"), name="unique_album_alias")]},
        ),
        migrations.CreateModel(
            name="SongAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("value", models.CharField(max_length=160)),
                ("normalized_value", models.CharField(db_index=True, max_length=160)),
                ("song", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="aliases", to="catalog.song")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("song", "value"), name="unique_song_alias")]},
        ),
    ]
