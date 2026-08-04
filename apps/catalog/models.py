from django.db import models
from django.urls import reverse


class Person(models.Model):
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    role = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Album(models.Model):
    title = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["release_year", "title"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("album-detail", kwargs={"slug": self.slug})


class AlbumAlias(models.Model):
    album = models.ForeignKey(Album, on_delete=models.CASCADE, related_name="aliases")
    value = models.CharField(max_length=160)
    normalized_value = models.CharField(max_length=160, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["album", "value"], name="unique_album_alias")
        ]

    def __str__(self) -> str:
        return self.value


class Song(models.Model):
    title = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    album = models.ForeignKey(
        Album, on_delete=models.SET_NULL, null=True, blank=True, related_name="songs"
    )
    release_year = models.PositiveSmallIntegerField(null=True, blank=True)
    is_b_side = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class SongAlias(models.Model):
    song = models.ForeignKey(Song, on_delete=models.CASCADE, related_name="aliases")
    value = models.CharField(max_length=160)
    normalized_value = models.CharField(max_length=160, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["song", "value"], name="unique_song_alias")
        ]

    def __str__(self) -> str:
        return self.value
