"""Image conversion via Pillow."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from formats.heif_support import register_heif_opener
from PIL import Image
from PIL.PngImagePlugin import PngInfo


class ImageConversionError(RuntimeError):
    """Raised when image conversion fails."""


@dataclass(frozen=True)
class ImageConversionTarget:
    label: str
    extension: str
    file_filter: str
    pil_format: str
    save_kwargs: dict[str, object] = field(default_factory=dict)


IMAGE_CONVERSION_TARGETS: tuple[ImageConversionTarget, ...] = (
    ImageConversionTarget(
        label="Convert to JPEG",
        extension=".jpg",
        file_filter="JPEG Image (*.jpg *.jpeg)",
        pil_format="JPEG",
        save_kwargs={"quality": 95, "subsampling": 0, "optimize": True},
    ),
    ImageConversionTarget(
        label="Convert to PNG",
        extension=".png",
        file_filter="PNG Image (*.png)",
        pil_format="PNG",
        save_kwargs={"optimize": True},
    ),
    ImageConversionTarget(
        label="Convert to HEIC",
        extension=".heic",
        file_filter="HEIC Image (*.heic)",
        pil_format="HEIF",
        save_kwargs={"quality": 90},
    ),
)


def ensure_output_path(path: Path, extension: str) -> Path:
    if path.suffix.lower() != extension:
        return path.with_suffix(extension)
    return path


def _prepare_image_for_format(image: Image.Image, pil_format: str) -> Image.Image:
    if pil_format == "JPEG" and image.mode in {"RGBA", "LA", "P"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode == "P":
            image = image.convert("RGBA")
        alpha = image.split()[-1] if "A" in image.mode else None
        background.paste(image, mask=alpha)
        return background
    if pil_format in {"PNG", "HEIF"} and image.mode not in {"RGB", "RGBA"}:
        return image.convert("RGBA" if pil_format == "PNG" else "RGB")
    return image


def convert_image(
    source: Path,
    destination: Path,
    target: ImageConversionTarget,
) -> None:
    register_heif_opener()
    destination = ensure_output_path(destination, target.extension)
    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with Image.open(source) as image:
            exif = image.getexif()
            png_info: PngInfo | None = None
            if target.pil_format == "PNG" and source.suffix.lower() == ".png":
                png_info = PngInfo()
                for key, value in image.info.items():
                    if isinstance(value, str):
                        png_info.add_text(key, value)

            prepared = _prepare_image_for_format(image, target.pil_format)
            save_kwargs = dict(target.save_kwargs)
            if exif:
                save_kwargs["exif"] = exif
            if target.pil_format == "PNG" and png_info is not None:
                save_kwargs["pnginfo"] = png_info

            prepared.save(destination, format=target.pil_format, **save_kwargs)
    except Exception as exc:
        if target.pil_format == "HEIF":
            raise ImageConversionError(
                "HEIC conversion requires pillow-heif. Install it with: pip install pillow-heif"
            ) from exc
        raise ImageConversionError(str(exc)) from exc

    if not destination.is_file():
        raise ImageConversionError("Conversion finished without creating an output file.")
