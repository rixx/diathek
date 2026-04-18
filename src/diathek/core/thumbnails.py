import hashlib
import io
from dataclasses import dataclass

from django.core.files.base import ContentFile
from PIL import Image as PILImage
from PIL import ImageOps

THUMB_SMALL_MAX = 300
THUMB_SMALL_QUALITY = 70
THUMB_DETAIL_MAX = 1600
THUMB_DETAIL_QUALITY = 80


@dataclass
class ImageAssets:
    content_hash: str
    file_size: int
    width: int
    height: int
    thumb_small: ContentFile
    thumb_detail: ContentFile | None


def _encode_webp(image, quality):
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="WEBP", quality=quality, method=6)
    return ContentFile(buffer.getvalue())


def build_assets(file_bytes):
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    with PILImage.open(io.BytesIO(file_bytes)) as opened:
        oriented = ImageOps.exif_transpose(opened) or opened
        width, height = oriented.size

        small = oriented.copy()
        small.thumbnail((THUMB_SMALL_MAX, THUMB_SMALL_MAX))
        thumb_small = _encode_webp(small, THUMB_SMALL_QUALITY)

        thumb_detail = None
        if max(width, height) > THUMB_DETAIL_MAX:
            detail = oriented.copy()
            detail.thumbnail((THUMB_DETAIL_MAX, THUMB_DETAIL_MAX))
            thumb_detail = _encode_webp(detail, THUMB_DETAIL_QUALITY)

    return ImageAssets(
        content_hash=content_hash,
        file_size=len(file_bytes),
        width=width,
        height=height,
        thumb_small=thumb_small,
        thumb_detail=thumb_detail,
    )
