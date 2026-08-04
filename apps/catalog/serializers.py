from rest_framework import serializers

from .models import Album, Person, Song


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ["id", "name", "slug", "role"]


class AlbumSerializer(serializers.ModelSerializer):
    class Meta:
        model = Album
        fields = ["id", "title", "slug", "release_year", "notes"]


class AlbumSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Album
        fields = ["id", "title", "slug", "release_year"]


class SongSerializer(serializers.ModelSerializer):
    album = AlbumSummarySerializer(read_only=True, allow_null=True)

    class Meta:
        model = Song
        fields = ["id", "title", "slug", "album", "release_year", "is_b_side", "notes"]


class SongSummarySerializer(serializers.ModelSerializer):
    album = AlbumSummarySerializer(read_only=True, allow_null=True)

    class Meta:
        model = Song
        fields = ["id", "title", "slug", "album", "release_year", "is_b_side"]


class MusicSongSerializer(serializers.ModelSerializer):
    class Meta:
        model = Song
        fields = ["id", "title", "slug", "is_b_side"]


class MusicAlbumSerializer(serializers.ModelSerializer):
    songs = MusicSongSerializer(many=True, read_only=True)

    class Meta:
        model = Album
        fields = ["id", "title", "slug", "release_year", "songs"]


class MusicCatalogSerializer(serializers.Serializer):
    albums = MusicAlbumSerializer(many=True)
    standalone_songs = MusicSongSerializer(many=True)
