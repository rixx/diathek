import hashlib
import io

import pytest
from PIL import Image as PILImage

from diathek.core.thumbnails import THUMB_DETAIL_MAX, THUMB_SMALL_MAX, build_assets
from tests.helpers import make_jpeg_bytes

pytestmark = pytest.mark.unit


def test_build_assets_computes_hash_dimensions_and_size():
    raw = make_jpeg_bytes(width=400, height=300)

    assets = build_assets(raw)

    assert assets.content_hash == hashlib.sha256(raw).hexdigest()
    assert assets.file_size == len(raw)
    assert assets.width == 400
    assert assets.height == 300


def test_build_assets_produces_small_webp_bounded_by_max_dim():
    raw = make_jpeg_bytes(width=800, height=600)

    assets = build_assets(raw)

    with PILImage.open(io.BytesIO(assets.thumb_small.read())) as img:
        assert img.format == "WEBP"
        assert max(img.size) <= THUMB_SMALL_MAX


def test_build_assets_skips_detail_when_original_is_small():
    raw = make_jpeg_bytes(width=600, height=400)

    assets = build_assets(raw)

    assert assets.thumb_detail is None


def test_build_assets_builds_detail_when_original_exceeds_detail_max():
    raw = make_jpeg_bytes(width=THUMB_DETAIL_MAX + 400, height=THUMB_DETAIL_MAX + 200)

    assets = build_assets(raw)

    assert assets.thumb_detail is not None
    with PILImage.open(io.BytesIO(assets.thumb_detail.read())) as img:
        assert img.format == "WEBP"
        assert max(img.size) <= THUMB_DETAIL_MAX
