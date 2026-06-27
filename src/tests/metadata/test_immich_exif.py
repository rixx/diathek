import datetime
from decimal import Decimal

from diathek.metadata.immich_exif import build_exiftool_args

DATE = datetime.date(2026, 4, 5)


def test_charset_is_always_first():
    args = build_exiftool_args()

    assert args[:2] == ["-charset", "IPTC=UTF8"]


def test_nothing_set_is_just_charset():
    assert build_exiftool_args() == ["-charset", "IPTC=UTF8"]


def test_date_present_writes_both_tags_at_noon():
    args = build_exiftool_args(date_representative=DATE)

    assert "-DateTimeOriginal=2026:04:05 12:00:00" in args
    assert "-CreateDate=2026:04:05 12:00:00" in args


def test_date_zero_pads_month_and_day():
    args = build_exiftool_args(date_representative=datetime.date(2026, 1, 9))

    assert "-DateTimeOriginal=2026:01:09 12:00:00" in args
    assert "-CreateDate=2026:01:09 12:00:00" in args


def test_date_absent_omits_both_tags():
    args = build_exiftool_args(date_representative=None)

    assert not any(arg.startswith("-DateTimeOriginal=") for arg in args)
    assert not any(arg.startswith("-CreateDate=") for arg in args)


def test_caption_from_date_display_only():
    args = build_exiftool_args(date_display="Sommer 1965")

    assert "-IPTC:Caption-Abstract=Sommer 1965" in args
    assert "-XMP-dc:Description=Sommer 1965" in args
    assert "-EXIF:UserComment=Sommer 1965" in args


def test_caption_from_description_only():
    args = build_exiftool_args(description="Opa im Garten")

    assert "-IPTC:Caption-Abstract=Opa im Garten" in args
    assert "-XMP-dc:Description=Opa im Garten" in args
    assert "-EXIF:UserComment=Opa im Garten" in args


def test_caption_joins_date_display_then_description_with_newline():
    args = build_exiftool_args(date_display="Sommer 1965", description="Opa im Garten")

    expected = "Sommer 1965\nOpa im Garten"
    assert "-IPTC:Caption-Abstract=" + expected in args
    assert "-XMP-dc:Description=" + expected in args
    assert "-EXIF:UserComment=" + expected in args


def test_caption_strips_each_part_before_joining():
    args = build_exiftool_args(date_display="  Sommer 1965 ", description="  Opa  ")

    assert "-IPTC:Caption-Abstract=Sommer 1965\nOpa" in args


def test_all_three_caption_tags_share_the_same_value():
    args = build_exiftool_args(date_display="Sommer 1965", description="Opa im Garten")

    values = [
        arg.split("=", 1)[1]
        for arg in args
        if arg.startswith(
            ("-IPTC:Caption-Abstract=", "-XMP-dc:Description=", "-EXIF:UserComment=")
        )
    ]
    assert len(values) == 3
    assert len(set(values)) == 1


def test_whitespace_only_caption_inputs_omit_caption_tags():
    args = build_exiftool_args(date_display="   ", description="\t\n ")

    assert not any(arg.startswith("-IPTC:Caption-Abstract=") for arg in args)
    assert not any(arg.startswith("-XMP-dc:Description=") for arg in args)
    assert not any(arg.startswith("-EXIF:UserComment=") for arg in args)


def test_default_caption_inputs_omit_caption_tags():
    assert build_exiftool_args() == ["-charset", "IPTC=UTF8"]


def test_place_name_writes_both_city_tags():
    args = build_exiftool_args(place_name="Weinheim")

    assert "-IPTC:City=Weinheim" in args
    assert "-XMP-photoshop:City=Weinheim" in args


def test_place_name_is_stripped():
    args = build_exiftool_args(place_name="  Weinheim  ")

    assert "-IPTC:City=Weinheim" in args
    assert "-XMP-photoshop:City=Weinheim" in args


def test_place_name_none_omits_city_tags():
    args = build_exiftool_args(place_name=None)

    assert not any(arg.startswith("-IPTC:City=") for arg in args)
    assert not any(arg.startswith("-XMP-photoshop:City=") for arg in args)


def test_place_name_whitespace_only_omits_city_tags():
    args = build_exiftool_args(place_name="   ")

    assert not any(arg.startswith("-IPTC:City=") for arg in args)
    assert not any(arg.startswith("-XMP-photoshop:City=") for arg in args)


def test_gps_both_positive_uses_north_east_refs():
    args = build_exiftool_args(latitude=49.5, longitude=8.6)

    assert "-GPSLatitude=49.5" in args
    assert "-GPSLatitudeRef=N" in args
    assert "-GPSLongitude=8.6" in args
    assert "-GPSLongitudeRef=E" in args


def test_gps_negative_uses_south_west_refs_and_absolute_values():
    args = build_exiftool_args(latitude=-34.6, longitude=-58.4)

    assert "-GPSLatitude=34.6" in args
    assert "-GPSLatitudeRef=S" in args
    assert "-GPSLongitude=58.4" in args
    assert "-GPSLongitudeRef=W" in args


def test_gps_zero_values_count_as_north_east():
    args = build_exiftool_args(latitude=0, longitude=0)

    assert "-GPSLatitudeRef=N" in args
    assert "-GPSLongitudeRef=E" in args


def test_gps_decimal_input_formats_sanely():
    args = build_exiftool_args(
        latitude=Decimal("49.546473"), longitude=Decimal("8.640815")
    )

    assert "-GPSLatitude=49.546473" in args
    assert "-GPSLongitude=8.640815" in args


def test_gps_only_latitude_omits_all_gps():
    args = build_exiftool_args(latitude=49.5, longitude=None)

    assert not any(arg.startswith("-GPS") for arg in args)


def test_gps_only_longitude_omits_all_gps():
    args = build_exiftool_args(latitude=None, longitude=8.6)

    assert not any(arg.startswith("-GPS") for arg in args)


def test_gps_both_none_omits_all_gps():
    args = build_exiftool_args()

    assert not any(arg.startswith("-GPS") for arg in args)


def test_needs_flip_true_writes_numeric_orientation():
    args = build_exiftool_args(needs_flip=True)

    assert "-Orientation#=2" in args


def test_needs_flip_false_omits_orientation():
    args = build_exiftool_args(needs_flip=False)

    assert not any(arg.startswith("-Orientation") for arg in args)


def test_everything_set():
    args = build_exiftool_args(
        date_representative=DATE,
        date_display="Sommer 1965",
        description="Opa im Garten",
        place_name="Weinheim",
        latitude=Decimal("-34.6"),
        longitude=Decimal("58.4"),
        needs_flip=True,
    )

    assert args == [
        "-charset",
        "IPTC=UTF8",
        "-DateTimeOriginal=2026:04:05 12:00:00",
        "-CreateDate=2026:04:05 12:00:00",
        "-IPTC:Caption-Abstract=Sommer 1965\nOpa im Garten",
        "-XMP-dc:Description=Sommer 1965\nOpa im Garten",
        "-EXIF:UserComment=Sommer 1965\nOpa im Garten",
        "-IPTC:City=Weinheim",
        "-XMP-photoshop:City=Weinheim",
        "-GPSLatitude=34.6",
        "-GPSLatitudeRef=S",
        "-GPSLongitude=58.4",
        "-GPSLongitudeRef=E",
        "-Orientation#=2",
    ]


def test_umlauts_survive_verbatim():
    args = build_exiftool_args(
        place_name="Müllheim", description="Tür zum Höfle, Größe"
    )

    assert "-IPTC:City=Müllheim" in args
    assert "-XMP-photoshop:City=Müllheim" in args
    assert "-IPTC:Caption-Abstract=Tür zum Höfle, Größe" in args
