import datetime
import hashlib
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.files.base import ContentFile

from diathek.core.immich_export import (
    ExiftoolError,
    build_args_for_image,
    render_processed_image,
    sha1_hex,
)
from tests.factories import ImageFactory, PlaceFactory

pytestmark = pytest.mark.django_db


def _stored_image(**kwargs):
    image = ImageFactory(**kwargs)
    image.image.save("scan.jpg", ContentFile(b"original-bytes"), save=False)
    return image


def test_build_args_for_image_reflects_full_model():
    place = PlaceFactory(
        name="Hamburg", latitude=Decimal("53.55"), longitude=Decimal("9.99")
    )
    image = ImageFactory(
        place=place,
        date_earliest=datetime.date(1990, 6, 1),
        date_latest=datetime.date(1990, 6, 30),
        date_display="Juni 1990",
        description="Oma im Garten",
        needs_flip=True,
    )

    args = build_args_for_image(image)

    assert "-IPTC:City=Hamburg" in args
    assert "-Orientation#=2" in args
    assert any(arg.startswith("-GPSLatitude=") for arg in args)
    assert any(arg.startswith("-DateTimeOriginal=") for arg in args)


def test_build_args_for_image_without_place_has_no_city_or_gps():
    image = ImageFactory(place=None)

    args = build_args_for_image(image)

    assert not any(arg.startswith("-IPTC:City=") for arg in args)
    assert not any(arg.startswith("-GPSLatitude=") for arg in args)


def test_render_processed_image_happy_path(mocker):
    image = _stored_image()
    run = mocker.patch("diathek.core.immich_export.subprocess.run")

    tmp_path = render_processed_image(image)

    try:
        assert tmp_path.exists()
        assert tmp_path.suffix == ".jpg"
        assert tmp_path.read_bytes() == b"original-bytes"
        command = run.call_args.args[0]
        assert command[0] == "exiftool"
        assert "-overwrite_original" in command
        assert command[-1] == str(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def test_render_processed_image_without_original_raises_value_error():
    image = ImageFactory()

    with pytest.raises(ValueError, match="no stored original"):
        render_processed_image(image)


def test_render_processed_image_exiftool_failure_cleans_up(mocker):
    image = _stored_image()
    captured = {}

    def fake_run(command, **_kwargs):
        captured["tmp_path"] = Path(command[-1])
        raise subprocess.CalledProcessError(1, command, stderr=b"boom")

    mocker.patch("diathek.core.immich_export.subprocess.run", side_effect=fake_run)

    with pytest.raises(ExiftoolError, match="boom"):
        render_processed_image(image)

    assert not captured["tmp_path"].exists()


def test_render_processed_image_missing_binary_cleans_up(mocker):
    image = _stored_image()
    captured = {}

    def fake_run(command, **_kwargs):
        captured["tmp_path"] = Path(command[-1])
        raise FileNotFoundError("exiftool")

    mocker.patch("diathek.core.immich_export.subprocess.run", side_effect=fake_run)

    with pytest.raises(ExiftoolError, match="not installed"):
        render_processed_image(image)

    assert not captured["tmp_path"].exists()


def test_render_processed_image_failure_without_stderr(mocker):
    image = _stored_image()

    def fake_run(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command, stderr=None)

    mocker.patch("diathek.core.immich_export.subprocess.run", side_effect=fake_run)

    with pytest.raises(ExiftoolError, match="exiftool failed"):
        render_processed_image(image)


def test_sha1_hex_matches_hashlib(tmp_path):
    data = b"some bytes for hashing" * 5000
    target = tmp_path / "blob.bin"
    target.write_bytes(data)

    assert sha1_hex(target) == hashlib.sha1(data).hexdigest()
