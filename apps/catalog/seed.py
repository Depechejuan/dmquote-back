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
    catalog_albums: int = 0
    catalog_songs: int = 0
    albums_created: int = 0
    albums_updated: int = 0
    songs_created: int = 0
    songs_updated: int = 0
    aliases_created: int = 0
    unmatched_existing_albums: list[str] | None = None
    unmatched_existing_songs: list[str] | None = None

    def __post_init__(self):
        self.unmatched_existing_albums = self.unmatched_existing_albums or []
        self.unmatched_existing_songs = self.unmatched_existing_songs or []


@dataclass(frozen=True)
class CatalogSong:
    title: str
    album: Album | None
    release_year: int | None
    aliases: list[str]
    legacy_titles: list[str]
    track_number: int | None
    track_number_provided: bool


def seed_catalog(path: str | Path, *, dry_run: bool = False) -> CatalogSeedSummary:
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8") as source_file:
        payload = json.load(source_file)
    version = str(payload.get("version", "unversioned"))
    albums_data = payload.get("albums")
    if not isinstance(albums_data, list):
        raise ValueError("Catalog JSON must contain an 'albums' list")
    standalone_data = payload.get("standalone_songs", [])
    if not isinstance(standalone_data, list):
        raise ValueError("Catalog JSON 'standalone_songs' must be a list")

    catalog_songs_data = collect_songs(
        albums_data,
        {} if dry_run else None,
        standalone_data,
    )
    validate_catalog(albums_data, catalog_songs_data)
    summary = CatalogSeedSummary(
        version=version,
        catalog_albums=len(albums_data),
        catalog_songs=len(catalog_songs_data),
    )
    if dry_run:
        summary.albums_created = len(albums_data)
        summary.songs_created = len(catalog_songs_data)
        summary.aliases_created = sum(
            len(album.get("aliases", []))
            + sum(
                len(song.get("aliases", [])) if isinstance(song, dict) else 0
                for song in album.get("songs", [])
            )
            for album in albums_data
        )
        summary.aliases_created += sum(
            len(song.aliases) for song in catalog_songs_data if song.album is None
        )
        summary.unmatched_existing_albums = unmatched_existing_albums(albums_data)
        summary.unmatched_existing_songs = unmatched_existing_songs(catalog_songs_data)
        return summary

    with transaction.atomic():
        albums = upsert_albums(albums_data, summary)
        summary.aliases_created += upsert_album_aliases(albums_data, albums)
        songs_data = collect_songs(albums_data, albums, standalone_data)
        songs = upsert_songs(songs_data, summary)
        summary.aliases_created += upsert_song_aliases(songs_data, songs)
        summary.unmatched_existing_albums = unmatched_existing_albums(albums_data)
        summary.unmatched_existing_songs = unmatched_existing_songs(songs_data)
    return summary


def upsert_albums(albums_data: list[dict], summary: CatalogSeedSummary) -> dict[str, Album]:
    titles = [album_data["title"] for album_data in albums_data]
    existing = {album.title: album for album in Album.objects.filter(title__in=titles)}
    used_slugs = set(Album.objects.values_list("slug", flat=True))
    new_albums = []
    for album_data in albums_data:
        title = album_data["title"]
        is_compilation = album_data.get("is_compilation", False)
        if not isinstance(is_compilation, bool):
            raise ValueError(f"Album is_compilation must be a boolean: {title!r}")
        if title in existing:
            summary.albums_updated += 1
            existing[title].release_year = album_data.get("release_year")
            if "is_compilation" in album_data:
                existing[title].is_compilation = is_compilation
            continue
        album = Album(
            title=title,
            slug=unique_slug(used_slugs, title),
            release_year=album_data.get("release_year"),
            is_compilation=is_compilation,
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
    Album.objects.bulk_update(all_albums.values(), ["release_year", "is_compilation"])
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


def collect_songs(
    albums_data: list[dict],
    albums: dict[str, Album] | None,
    standalone_data: list[dict] | None = None,
) -> list[CatalogSong]:
    songs: list[CatalogSong] = []
    for album_data in albums_data:
        for track_number, song_data in enumerate(album_data.get("songs", []), start=1):
            songs.append(
                catalog_song(
                    song_data,
                    albums.get(album_data["title"]) if albums is not None else None,
                    album_data.get("release_year"),
                    track_number,
                )
            )
    for song_data in standalone_data or []:
        default_year = song_data.get("release_year") if isinstance(song_data, dict) else None
        songs.append(catalog_song(song_data, None, default_year, None))
    return songs


def catalog_song(
    song_data,
    album: Album | None,
    default_release_year: int | None,
    default_track_number: int | None,
) -> CatalogSong:
    if isinstance(song_data, str):
        return CatalogSong(
            song_data,
            album,
            default_release_year,
            [],
            [],
            default_track_number,
            False,
        )
    if not isinstance(song_data, dict) or not song_data.get("title"):
        raise ValueError("Each catalog song must be a title or an object with a title")
    track_number = song_data.get("track_number", default_track_number)
    if track_number is not None and (
        isinstance(track_number, bool)
        or not isinstance(track_number, int)
        or track_number < 1
    ):
        raise ValueError(f"Song track_number must be a positive integer: {song_data['title']!r}")
    return CatalogSong(
        title=song_data["title"],
        album=album,
        release_year=song_data.get("release_year", default_release_year),
        aliases=list(song_data.get("aliases", [])),
        legacy_titles=list(song_data.get("legacy_titles", [])),
        track_number=track_number,
        track_number_provided="track_number" in song_data,
    )


def validate_catalog(albums_data: list[dict], songs_data: list[CatalogSong]) -> None:
    seen: dict[str, str] = {}
    for song in songs_data:
        for label in [song.title, *song.aliases, *song.legacy_titles]:
            normalized = normalize_catalog_value(label)
            if not normalized:
                raise ValueError(f"Catalog title cannot be empty: {label!r}")
            previous = seen.get(normalized)
            if previous and previous != song.title:
                raise ValueError(
                    f"Duplicate normalized song title in catalog: {label!r} "
                    f"belongs to both {previous!r} and {song.title!r}"
                )
            seen[normalized] = song.title


def upsert_songs(songs_data: list[CatalogSong], summary: CatalogSeedSummary) -> dict[str, Song]:
    existing_songs = list(Song.objects.all())
    existing_by_title = {song.title: song for song in existing_songs}
    existing_by_normalized = {
        normalize_catalog_value(song.title): song for song in existing_songs
    }
    used_slugs = set(Song.objects.values_list("slug", flat=True))
    new_songs = []
    all_songs: dict[str, Song] = {}
    for catalog_song_data in songs_data:
        title = catalog_song_data.title
        existing = existing_by_title.get(title)
        if existing is None:
            existing = existing_by_normalized.get(normalize_catalog_value(title))
        if existing is None:
            existing = next(
                (
                    candidate
                    for legacy_title in catalog_song_data.legacy_titles
                    for candidate in [existing_by_title.get(legacy_title)]
                    if candidate is not None
                ),
                None,
            )
        if existing is not None:
            summary.songs_updated += 1
            if existing.title != title:
                used_slugs.discard(existing.slug)
                existing.title = title
                existing.slug = unique_slug(used_slugs, title)
                used_slugs.add(existing.slug)
            existing.album = catalog_song_data.album
            existing.release_year = catalog_song_data.release_year
            if catalog_song_data.track_number_provided or existing.track_number is None:
                existing.track_number = catalog_song_data.track_number
            all_songs[title] = existing
            continue
        song = Song(
            title=title,
            slug=unique_slug(used_slugs, title),
            album=catalog_song_data.album,
            release_year=catalog_song_data.release_year,
            track_number=catalog_song_data.track_number,
        )
        used_slugs.add(song.slug)
        new_songs.append(song)
        all_songs[title] = song
        summary.songs_created += 1
    if new_songs:
        Song.objects.bulk_create(new_songs)
    Song.objects.bulk_update(
        all_songs.values(), ["title", "slug", "album", "release_year", "track_number"]
    )
    return all_songs


def upsert_song_aliases(songs_data: list[CatalogSong], songs: dict[str, Song]) -> int:
    requested = [
        (songs[song.title].pk, alias)
        for song in songs_data
        for alias in song.aliases
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


def unmatched_existing_albums(albums_data: list[dict]) -> list[str]:
    catalog_titles = {normalize_catalog_value(album["title"]) for album in albums_data}
    return sorted(
        album.title
        for album in Album.objects.all()
        if normalize_catalog_value(album.title) not in catalog_titles
    )


def unmatched_existing_songs(songs_data: list[CatalogSong]) -> list[str]:
    catalog_titles = {
        normalize_catalog_value(label)
        for song in songs_data
        for label in [song.title, *song.legacy_titles]
    }
    return sorted(
        song.title
        for song in Song.objects.all()
        if normalize_catalog_value(song.title) not in catalog_titles
    )


def unique_slug(used_slugs: set[str], title: str) -> str:
    base = slugify(title)[:170] or "entity"
    candidate = base
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate[:180]
