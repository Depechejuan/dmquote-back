from django.contrib import admin

from .models import Album, AlbumAlias, Person, Song, SongAlias


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "is_active")
    search_fields = ("name", "role")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ("title", "release_year", "is_compilation")
    list_filter = ("is_compilation",)
    search_fields = ("title", "aliases__value")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(AlbumAlias)
class AlbumAliasAdmin(admin.ModelAdmin):
    list_display = ("value", "album", "normalized_value")
    search_fields = ("value", "album__title")


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    list_display = ("title", "album", "release_year", "is_b_side")
    list_filter = ("is_b_side", "album")
    search_fields = ("title", "aliases__value", "album__title")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(SongAlias)
class SongAliasAdmin(admin.ModelAdmin):
    list_display = ("value", "song", "normalized_value")
    search_fields = ("value", "song__title")
