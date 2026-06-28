from rest_framework import serializers

from diathek.core.models import Image, Place


class ImageSerializer(serializers.ModelSerializer):
    """Read representation of an image and its current metadata.

    Writes do not go through this serializer — the metadata-update path reuses
    the same liberal parsing (place-by-name, free-text date) as the web UI, so
    the view handles it directly. See ``WRITABLE_FIELDS`` in ``api.views``.
    """

    box = serializers.SlugRelatedField(slug_field="uuid", read_only=True)
    box_name = serializers.CharField(source="box.name", read_only=True, default=None)
    place = serializers.CharField(source="place.name", read_only=True, default=None)

    class Meta:
        model = Image
        fields = [
            "id",
            "uuid",
            "filename",
            "box",
            "box_name",
            "sequence_in_box",
            "place",
            "latitude",
            "longitude",
            "place_todo",
            "date_earliest",
            "date_latest",
            "date_precision",
            "date_display",
            "date_todo",
            "needs_flip",
            "edit_todo",
            "description",
            "version",
            "immich_asset_id",
            "immich_uploaded_at",
        ]
        read_only_fields = fields


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = ["id", "name", "latitude", "longitude"]
        read_only_fields = fields
