from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


IMAGE_SIZE_PIXELS = {
    "small": 1080,
    "medium": 2160,
    "large": 3160,
}

IMAGE_FORMATS = {"jpeg", "png", "webp", "avif"}
VIDEO_FORMATS = {"mp4", "webm", "mov", "gif"}


class ActionError(ValueError):
    pass


def unique_output(source: Path, label: str, extension: str) -> Path:
    extension = extension.casefold().lstrip(".")
    stem = source.stem
    candidate = source.with_name(f"{stem}-{label}.{extension}")
    number = 2
    while candidate.exists() or candidate == source:
        candidate = source.with_name(f"{stem}-{label}-{number}.{extension}")
        number += 1
    return candidate


def image_resize_command(source: Path, size: str) -> tuple[list[str], Path]:
    if size not in IMAGE_SIZE_PIXELS:
        raise ActionError(f"Unknown image size: {size}")
    extension = source.suffix.casefold().lstrip(".") or "png"
    output = unique_output(source, size, extension)
    pixels = IMAGE_SIZE_PIXELS[size]
    return (
        [
            "magick",
            str(source),
            "-auto-orient",
            "-resize",
            f"{pixels}x{pixels}>",
            "-strip",
            str(output),
        ],
        output,
    )


def image_convert_command(source: Path, image_format: str) -> tuple[list[str], Path]:
    image_format = image_format.casefold()
    if image_format not in IMAGE_FORMATS:
        raise ActionError(f"Unknown image format: {image_format}")
    extension = "jpg" if image_format == "jpeg" else image_format
    output = unique_output(source, f"converted-{extension}", extension)
    quality = {
        "jpeg": ["-quality", "85"],
        "png": ["-define", "png:compression-level=8"],
        "webp": ["-quality", "82"],
        "avif": ["-quality", "55"],
    }[image_format]
    return ["magick", str(source), "-auto-orient", "-strip", *quality, str(output)], output


def video_convert_command(source: Path, video_format: str) -> tuple[list[str], Path]:
    video_format = video_format.casefold()
    if video_format not in VIDEO_FORMATS:
        raise ActionError(f"Unknown video format: {video_format}")
    output = unique_output(source, f"converted-{video_format}", video_format)
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    options = {
        "mp4": [
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        ],
        "webm": [
            "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
            "-c:a", "libopus", "-b:a", "128k",
        ],
        "mov": ["-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s16le"],
        "gif": [
            "-vf",
            "fps=10,scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(720,ih))':flags=lanczos",
            "-loop", "0",
        ],
    }[video_format]
    return [*base, *options, str(output)], output


def normalize_nas_uri(value: str) -> str:
    uri = value.strip()
    if "://" not in uri:
        uri = f"smb://{uri.lstrip('/')}"
    parsed = urlparse(uri)
    if parsed.scheme.casefold() not in {"smb", "smbs", "nfs"}:
        raise ActionError("Use an smb:// or nfs:// address")
    if not parsed.netloc:
        raise ActionError("Enter a server and share path")
    if parsed.scheme.casefold() in {"smb", "smbs"} and not parsed.path.strip("/"):
        raise ActionError("Enter an SMB share, for example smb://nas/media")
    return uri
