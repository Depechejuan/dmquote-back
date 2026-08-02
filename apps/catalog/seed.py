from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils.text import slugify

from .models import Album, AlbumAlias, Song, SongAlias
from .normalization import normalize_catalog_value


@dataclass
class CatalogSeedSummary:
    version: str
    albums_created: int = 0
    albums_updated: int = 0
    songs_created: int = 0
    songs_updated: int = 0
    aliases_created: int = 0


def seed_catalog(path: str | Path, *, dry_run: bool = False) -> CatalogSeedSummary:
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8") as source_file:
        payload = json.load(source_file)
    version = str(payload.get("version", "unversioned"))
    albums_data = payload.get("albums")
    if not isinstance(albums_data, list):
        raise ValueError("Catalog JSON must contain an 'albums' list")

    summary = CatalogSeedSummary(version=version)
    if dry_run:
        summary.albums_created = len(albums_data)
        summary.songs_created = sum(len(album.get("songs", [])) for album in albums_data)
        summary.aliases_created = sum(
            len(album.get("aliases", []))
            + sum(
                len(song.get("aliases", []))
                for song in album.get("songs", [])
                if isinstance(song, dict)
            )
            for album in albums_data
        )
        return summary

    with transaction.atomic():
        albums = upsert_albums(albums_data, summary)
        summary.aliases_created += upsert_album_aliases(albums_data, albums)
        songs_data = collect_songs(albums_data, albums)
        songs = upsert_songs(songs_data, summary)
        summary.aliases_created += upsert_song_aliases(songs_data, songs)
    return summary


def upsert_albums(albums_data: list[dict], summary: CatalogSeedSummary) -> dict[str, Album]:
    titles = [album_data["title"] for album_data in albums_data]
    existing = {album.title: album for album in Album.objects.filter(title__in=titles)}
    used_slugs = set(Album.objects.values_list("slug", flat=True))
    new_albums = []
    for album_data in albums_data:
        title = album_data["title"]
        if title in existing:
            summary.albums_updated += 1
            existing[title].release_year = album_data.get("release_year")
            continue
        album = Album(
            title=title,
            slug=unique_slug(used_slugs, title),
            release_year=album_data.get("release_year"),
        )
        used_slugs.add(album.slug)
        new_albums.append(album)
        existing[title] = album
        summary.albums_created += 1
    if new_albums:
        Album.objects.bulk_create(new_albums)
    all_albums = {album.title: album for album in Album.objects.filter(title__in=titles)}
    for title, album in existing.items():
        if album.pk:
            album.release_year = next(
                item.get("release_year") for item in albums_data if item["title"] == title
            )
    Album.objects.bulk_update(all_albums.values(), ["release_year"])
    return all_albums


def upsert_album_aliases(albums_data: list[dict], albums: dict[str, Album]) -> int:
    requested = [
        (albums[album_data["title"]].pk, alias)
        for album_data in albums_data
        for alias in album_data.get("aliases", [])
    ]
    existing = set(
        AlbumAlias.objects.filter(album_id__in=[album.pk for album in albums.values()]).values_list(
            "album_id", "value"
        )
    )
    new_aliases = [
        AlbumAlias(album_id=album_id, value=value, normalized_value=normalize_catalog_value(value))
        for album_id, value in requested
        if (album_id, value) not in existing
    ]
    if new_aliases:
        AlbumAlias.objects.bulk_create(new_aliases, ignore_conflicts=True)
    return len(new_aliases)


def collect_songs(albums_data: list[dict], albums: dict[str, Album]) -> list[tuple[str, Album, list[str]]]:
    songs = []
    seen_titles = set()
    for album_data in albums_data:
        for song_data in album_data.get("songs", []):
            title = song_data if isinstance(song_data, str) else song_data["title"]
            if title in seen_titles:
                raise ValueError(f"Duplicate song title in catalog: {title}")
            seen_titles.add(title)
            aliases = [] if isinstance(song_data, str) else song_data.get("aliases", [])
            songs.append((title, albums[album_data["title"]], aliases))
    return songs


def upsert_songs(songs_data: list[tuple[str, Album, list[str]]], summary: CatalogSeedSummary) -> dict[str, Song]:
    titles = [title for title, _, _ in songs_data]
    existing = {song.title: song for song in Song.objects.filter(title__in=titles)}
    used_slugs = set(Song.objects.values_list("slug", flat=True))
    new_songs = []
    for title, album, _ in songs_data:
        if title in existing:
            summary.songs_updated += 1
            existing[title].album = album
            existing[title].release_year = album.release_year
            continue
        song = Song(
            title=title,
            slug=unique_slug(used_slugs, title),
            album=album,
            release_year=album.release_year,
        )
        used_slugs.add(song.slug)
        new_songs.append(song)
        existing[title] = song
        summary.songs_created += 1
    if new_songs:
        Song.objects.bulk_create(new_songs)
    all_songs = {song.title: song for song in Song.objects.filter(title__in=titles)}
    for title, album, _ in songs_data:
        all_songs[title].album = album
        all_songs[title].release_year = album.release_year
    Song.objects.bulk_update(all_songs.values(), ["album", "release_year"])
    return all_songs


def upsert_song_aliases(songs_data: list[tuple[str, Album, list[str]]], songs: dict[str, Song]) -> int:
    requested = [
        (songs[title].pk, alias)
        for title, _, aliases in songs_data
        for alias in aliases
    ]
    existing = set(
        SongAlias.objects.filter(song_id__in=[song.pk for song in songs.values()]).values_list(
            "song_id", "value"
        )
    )
    new_aliases = [
        SongAlias(song_id=song_id, value=value, normalized_value=normalize_catalog_value(value))
        for song_id, value in requested
        if (song_id, value) not in existing
    ]
    if new_aliases:
        SongAlias.objects.bulk_create(new_aliases, ignore_conflicts=True)
    return len(new_aliases)


def unique_slug(used_slugs: set[str], title: str) -> str:
    base = slugify(title)[:170] or "entity"
    candidate = base
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate[:180]
