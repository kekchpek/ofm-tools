"""OFM Factory: payload from source, format and metadata from the donor."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.errors import ConversionError, TransferError
from core.factory import build_factory_result, factory_output_name, normalize_output_name


def _png(path: Path, size: tuple[int, int], colour: tuple[int, int, int]) -> Path:
    Image.new("RGB", size, colour).save(path, format="PNG")
    return path


def _jpeg_with_exif(path: Path, size: tuple[int, int], make: str) -> Path:
    exif = Image.Exif()
    exif[271] = make  # Make
    exif[272] = "Model-X"  # Model
    Image.new("RGB", size, (10, 10, 200)).save(path, format="JPEG", exif=exif)
    return path


def test_output_name_uses_source_stem_and_donor_suffix(tmp_path):
    name = factory_output_name(tmp_path / "clip.png", tmp_path / "donor.HEIC")
    assert name == "clip_ofm.heic"


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("holiday", "holiday.jpg"),
        ("holiday.jpg", "holiday.jpg"),
        ("holiday.png", "holiday.jpg"),  # wrong extension is corrected, not trusted
        ("  spaced  ", "spaced.jpg"),
        ("", "fallback.jpg"),
        ("   ", "fallback.jpg"),
        ("../../etc/passwd", "passwd.jpg"),  # no path traversal
        ("nested/dir/name.heic", "name.jpg"),
    ],
)
def test_normalize_output_name(requested, expected, tmp_path):
    donor = tmp_path / "donor.JPG"
    assert normalize_output_name(requested, donor, fallback_stem="fallback") == expected


@pytest.mark.parametrize(
    ("requested", "donor_name", "expected"),
    [
        # The reported bug: an already-correct name gained a second extension.
        ("IMG_0118.HEIC", "donor.heic", "IMG_0118.HEIC"),
        ("IMG_0118.heic", "donor.HEIC", "IMG_0118.heic"),
        ("photo.JPG", "donor.jpg", "photo.JPG"),
        ("clip.mov", "donor.MOV", "clip.mov"),
        # Only a trailing match counts. Here ".photo" is the trailing segment,
        # so it is replaced like any other wrong extension.
        ("my.heic.photo", "donor.heic", "my.heic.heic"),
        # Bare extension with nothing before it falls back rather than hiding the file.
        (".heic", "donor.heic", "fallback.heic"),
    ],
)
def test_normalize_output_name_does_not_double_the_extension(
    requested, donor_name, expected, tmp_path
):
    donor = tmp_path / donor_name
    assert normalize_output_name(requested, donor, fallback_stem="fallback") == expected


def test_image_result_takes_payload_from_source(tmp_path):
    source = _png(tmp_path / "source.png", (64, 48), (220, 30, 70))
    donor = _jpeg_with_exif(tmp_path / "donor.jpg", (16, 16), "ACME")
    result = tmp_path / "result.jpg"

    build_factory_result(source, donor, result)

    with Image.open(result) as image:
        assert image.size == (64, 48), "payload should come from the source"
        assert image.format == "JPEG", "format should come from the donor"


def test_image_result_takes_metadata_from_donor(tmp_path):
    source = _png(tmp_path / "source.png", (64, 48), (220, 30, 70))
    donor = _jpeg_with_exif(tmp_path / "donor.jpg", (16, 16), "ACME")
    result = tmp_path / "result.jpg"

    build_factory_result(source, donor, result)

    with Image.open(result) as image:
        exif = image.getexif()
    assert exif.get(271) == "ACME"
    assert exif.get(272) == "Model-X"


def test_no_conversion_when_formats_already_match(tmp_path):
    source = _jpeg_with_exif(tmp_path / "source.jpg", (64, 48), "SourceCam")
    donor = _jpeg_with_exif(tmp_path / "donor.jpg", (16, 16), "DonorCam")
    result = tmp_path / "result.jpg"

    build_factory_result(source, donor, result)

    with Image.open(result) as image:
        assert image.size == (64, 48)
        assert image.getexif().get(271) == "DonorCam"


def test_intermediate_files_are_cleaned_up(tmp_path):
    source = _png(tmp_path / "source.png", (32, 32), (1, 2, 3))
    donor = _jpeg_with_exif(tmp_path / "donor.jpg", (8, 8), "ACME")
    result = tmp_path / "result.jpg"

    build_factory_result(source, donor, result)

    leftovers = {path.name for path in tmp_path.iterdir()}
    assert leftovers == {"source.png", "donor.jpg", "result.jpg"}


def test_mixing_image_and_video_is_rejected(tmp_path):
    source = _png(tmp_path / "source.png", (32, 32), (1, 2, 3))
    donor = tmp_path / "donor.mov"
    donor.write_bytes(b"\x00" * 32)

    with pytest.raises(TransferError, match="same media type"):
        build_factory_result(source, donor, tmp_path / "result.mov")


def test_unsupported_source_is_rejected(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("nope")
    donor = _jpeg_with_exif(tmp_path / "donor.jpg", (8, 8), "ACME")

    with pytest.raises(ConversionError, match="[Ss]ource"):
        build_factory_result(source, donor, tmp_path / "result.jpg")


def test_unsupported_donor_is_rejected(tmp_path):
    source = _png(tmp_path / "source.png", (32, 32), (1, 2, 3))
    donor = tmp_path / "donor.txt"
    donor.write_text("nope")

    with pytest.raises(ConversionError, match="metadata"):
        build_factory_result(source, donor, tmp_path / "result.jpg")


# --- video, using the checked-out sample media -----------------------------


def test_video_result_carries_donor_metadata(tmp_path, video6_target, video6_source):
    """A real MOV donor's metadata atoms should replace the source's."""
    from core.inspect import inspect_layout

    result = tmp_path / "result.mov"
    build_factory_result(video6_target, video6_source, result)

    def metadata_bytes(path: Path) -> int:
        return sum(s.size for s in inspect_layout(path).segments if s.category == "metadata")

    donor_bytes = metadata_bytes(video6_source)
    assert donor_bytes > 0
    assert metadata_bytes(result) == donor_bytes
