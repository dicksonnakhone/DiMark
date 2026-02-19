"""Image processing utilities for ad platform creative assets.

Provides download, validation, optimisation and hashing for images that will
be uploaded to advertising platforms (Meta, Google, etc.).
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from typing import Any

import httpx
from PIL import Image

from app.platforms.exceptions import ImageDownloadError, ImageValidationError

# ---------------------------------------------------------------------------
# Constants — Meta image requirements
# ---------------------------------------------------------------------------

META_MAX_IMAGE_SIZE_BYTES: int = 30 * 1024 * 1024  # 30 MB
META_MIN_DIMENSION: int = 600  # pixels
META_SUPPORTED_FORMATS: set[str] = {"JPEG", "PNG", "BMP", "TIFF", "GIF"}

# ---------------------------------------------------------------------------
# ImageProcessor
# ---------------------------------------------------------------------------


class ImageProcessor:
    """Download, validate, optimise, and hash images for ad platforms."""

    # ------------------------------------------------------------------
    # download
    # ------------------------------------------------------------------

    async def download_image(self, url: str, *, timeout: float = 30.0) -> bytes:
        """Download an image from *url* and return its bytes.

        Validates that the response content-type starts with ``image/``.
        Raises :class:`ImageDownloadError` on failure.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(url, timeout=timeout)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImageDownloadError(
                f"Failed to download image from {url}: {exc}",
                details={"url": url, "error": str(exc)},
            ) from exc

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ImageDownloadError(
                f"URL did not return an image (content-type: {content_type})",
                details={"url": url, "content_type": content_type},
            )

        return response.content

    def download_image_sync(self, url: str, *, timeout: float = 30.0) -> bytes:
        """Synchronous variant used inside ``asyncio.to_thread`` contexts."""
        try:
            with httpx.Client(follow_redirects=True) as client:
                response = client.get(url, timeout=timeout)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ImageDownloadError(
                f"Failed to download image from {url}: {exc}",
                details={"url": url, "error": str(exc)},
            ) from exc

        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            raise ImageDownloadError(
                f"URL did not return an image (content-type: {content_type})",
                details={"url": url, "content_type": content_type},
            )

        return response.content

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------

    def validate_image(self, data: bytes) -> dict[str, Any]:
        """Validate image bytes against platform requirements.

        Returns a dict with ``is_valid``, ``format``, ``width``, ``height``,
        ``size_bytes``, and ``issues`` (list of problem descriptions).

        Raises :class:`ImageValidationError` for corrupt or empty data.
        """
        if not data:
            raise ImageValidationError(
                "Image data is empty",
                details={"size_bytes": 0},
            )

        try:
            img = Image.open(io.BytesIO(data))
            img.verify()  # verify integrity without loading pixel data
            # Re-open after verify (verify closes the file)
            img = Image.open(io.BytesIO(data))
        except Exception as exc:
            raise ImageValidationError(
                f"Image data is corrupt or unreadable: {exc}",
                details={"error": str(exc)},
            ) from exc

        fmt = img.format or "UNKNOWN"
        width, height = img.size
        size_bytes = len(data)
        issues: list[str] = []

        if fmt not in META_SUPPORTED_FORMATS:
            issues.append(
                f"Unsupported format '{fmt}'. Supported: {', '.join(sorted(META_SUPPORTED_FORMATS))}"
            )

        if width < META_MIN_DIMENSION or height < META_MIN_DIMENSION:
            issues.append(
                f"Image dimensions {width}x{height} are below the minimum "
                f"{META_MIN_DIMENSION}x{META_MIN_DIMENSION}"
            )

        if size_bytes > META_MAX_IMAGE_SIZE_BYTES:
            issues.append(
                f"Image size {size_bytes:,} bytes exceeds maximum "
                f"{META_MAX_IMAGE_SIZE_BYTES:,} bytes"
            )

        return {
            "format": fmt,
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "is_valid": len(issues) == 0,
            "issues": issues,
        }

    # ------------------------------------------------------------------
    # optimise
    # ------------------------------------------------------------------

    def optimize_image(
        self,
        data: bytes,
        *,
        max_width: int | None = None,
        max_height: int | None = None,
        target_format: str | None = None,
    ) -> bytes:
        """Resize and/or reformat an image, returning optimised bytes.

        - Uses ``Image.thumbnail()`` with LANCZOS resampling for downscaling.
        - Converts RGBA → RGB (white background) when saving as JPEG.
        - If no resizing or format change is needed, returns compressed bytes.
        """
        img = Image.open(io.BytesIO(data))

        # Resize if needed
        if max_width or max_height:
            w = max_width or img.width
            h = max_height or img.height
            img.thumbnail((w, h), Image.LANCZOS)

        # Determine output format
        out_format = (target_format or img.format or "PNG").upper()
        if out_format == "JPG":
            out_format = "JPEG"

        # Convert RGBA to RGB for JPEG
        if out_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background

        buf = io.BytesIO()
        save_kwargs: dict[str, Any] = {}
        if out_format == "JPEG":
            save_kwargs["quality"] = 85
            save_kwargs["optimize"] = True
        elif out_format == "PNG":
            save_kwargs["optimize"] = True

        img.save(buf, format=out_format, **save_kwargs)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # hash
    # ------------------------------------------------------------------

    @staticmethod
    def compute_hash(data: bytes) -> str:
        """Return the SHA-256 hex digest of *data*."""
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------
    # temp file
    # ------------------------------------------------------------------

    @staticmethod
    def save_to_tempfile(data: bytes, *, suffix: str = ".png") -> str:
        """Write *data* to a named temporary file and return the path.

        The caller is responsible for calling ``os.unlink(path)`` when done.
        """
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return path
