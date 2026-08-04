from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.shortcuts import redirect, render

from .models import Album, AlbumAlias, Person, Song, SongAlias


class AssignSongsToReleaseForm(forms.Form):
    album = forms.ModelChoiceField(
        label="Album or compilation",
        queryset=Album.objects.order_by("is_compilation", "release_year", "title"),
        empty_label="Select an album or compilation",
    )


@admin.action(description="Assign selected songs to an album or compilation")
def assign_selected_songs_to_release(modeladmin, request, queryset):
    form = AssignSongsToReleaseForm(request.POST or None)
    if request.POST.get("apply") and form.is_valid():
        album = form.cleaned_data["album"]
        changed = queryset.update(album=album)
        modeladmin.message_user(
            request,
            f"{changed} song(s) assigned to {album}.",
            messages.SUCCESS,
        )
        return redirect("admin:catalog_song_changelist")

    context = {
        **modeladmin.admin_site.each_context(request),
        "opts": modeladmin.model._meta,
        "title": "Assign songs to an album or compilation",
        "form": form,
        "selected_songs": queryset.select_related("album"),
        "selected_ids": request.POST.getlist(helpers.ACTION_CHECKBOX_NAME),
        "select_across": request.POST.get("select_across", "0"),
        "action_name": "assign_selected_songs_to_release",
    }
    return render(request, "admin/catalog/song/assign_album.html", context)


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
    list_display = ("title", "album", "track_number", "release_year", "is_b_side")
    list_editable = ("track_number",)
    list_filter = ("is_b_side", "album")
    search_fields = ("title", "aliases__value", "album__title")
    prepopulated_fields = {"slug": ("title",)}
    list_select_related = ("album",)
    actions = [assign_selected_songs_to_release]


@admin.register(SongAlias)
class SongAliasAdmin(admin.ModelAdmin):
    list_display = ("value", "song", "normalized_value")
    search_fields = ("value", "song__title")
