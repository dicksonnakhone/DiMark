"""Tests for the ImageProcessor utility class."""

import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.platforms.exceptions import ImageDownloadError, ImageValidationError
from app.utils.image_utils import (
    META_MIN_DIMENSION,
    META_SUPPORTED_FORMATS,
    ImageProcessor,
)


# ---------------------------------------------------------------------------
# Helpers — create synthetic test images in memory
# ---------------------------------------------------------------------------


def _make_image(
    width: int = 800,
    height: int = 800,
    fmt: str = "PNG",
    mode: str = "RGB",
) -> bytes:
    """Create a synthetic image and return it as bytes."""
    img = Image.new(mode, (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    if fmt == "JPEG" and mode == "RGBA":
        # JPEG doesn't support RGBA — convert first
        img = img.convert("RGB")
    img.save(buf, format=fmt)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def processor():
    return ImageProcessor()


# ---------------------------------------------------------------------------
# validate_image tests
# ---------------------------------------------------------------------------


def test_validate_valid_png(processor):
    data = _make_image(fmt="PNG")
    info = processor.validate_image(data)
    assert info["is_valid"] is True
    assert info["format"] == "PNG"
    assert info["width"] == 800
    assert info["height"] == 800
    assert len(info["issues"]) == 0


def test_validate_valid_jpeg(processor):
    data = _make_image(fmt="JPEG")
    info = processor.validate_image(data)
    assert info["is_valid"] is True
    assert info["format"] == "JPEG"


def test_validate_too_small(processor):
    data = _make_image(width=200, height=200)
    info = processor.validate_image(data)
    assert info["is_valid"] is False
    assert any("below" in issue.lower() or "dimensions" in issue.lower() for issue in info["issues"])


def test_validate_corrupt_data(processor):
    with pytest.raises(ImageValidationError, match="corrupt"):
        processor.validate_image(b"this is not an image")


def test_validate_empty_bytes(processor):
    with pytest.raises(ImageValidationError, match="empty"):
        processor.validate_image(b"")


# ---------------------------------------------------------------------------
# optimize_image tests
# ---------------------------------------------------------------------------


def test_optimize_preserves_small_image(processor):
    """An already-valid image should still produce valid output."""
    data = _make_image(width=800, height=800, fmt="PNG")
    optimised = processor.optimize_image(data)
    assert len(optimised) > 0
    # Verify it's still a valid image
    img = Image.open(io.BytesIO(optimised))
    assert img.width <= 800
    assert img.height <= 800


def test_optimize_resizes_large_image(processor):
    """A very large image should be resized down."""
    data = _make_image(width=4000, height=2000, fmt="PNG")
    optimised = processor.optimize_image(data, max_width=1200, max_height=1200)
    img = Image.open(io.BytesIO(optimised))
    assert img.width <= 1200
    assert img.height <= 1200


def test_optimize_converts_rgba_to_rgb(processor):
    """RGBA → JPEG should produce RGB output."""
    data = _make_image(width=800, height=800, fmt="PNG", mode="RGBA")
    optimised = processor.optimize_image(data, target_format="JPEG")
    img = Image.open(io.BytesIO(optimised))
    assert img.mode == "RGB"
    assert img.format == "JPEG"


# ---------------------------------------------------------------------------
# compute_hash tests
# ---------------------------------------------------------------------------


def test_hash_deterministic(processor):
    data = _make_image()
    h1 = processor.compute_hash(data)
    h2 = processor.compute_hash(data)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_different_images(processor):
    data1 = _make_image(width=800, height=800)
    data2 = _make_image(width=900, height=900)
    assert processor.compute_hash(data1) != processor.compute_hash(data2)


# ---------------------------------------------------------------------------
# save_to_tempfile tests
# ---------------------------------------------------------------------------


def test_save_to_tempfile(processor):
    data = b"test image data"
    path = processor.save_to_tempfile(data, suffix=".png")
    try:
        assert os.path.exists(path)
        assert path.endswith(".png")
        with open(path, "rb") as f:
            assert f.read() == data
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# download_image (async) tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_success(processor):
    """Async download with mocked httpx.AsyncClient."""
    fake_image = _make_image()
    mock_response = MagicMock()
    mock_response.content = fake_image
    mock_response.headers = {"content-type": "image/png"}
    mock_response.raise_for_status = MagicMock()

    with patch("app.utils.image_utils.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await processor.download_image("https://example.com/img.png")
        assert result == fake_image


@pytest.mark.asyncio
async def test_download_non_image_content_type(processor):
    """Should raise ImageDownloadError for non-image content types."""
    mock_response = MagicMock()
    mock_response.content = b"<html>not an image</html>"
    mock_response.headers = {"content-type": "text/html"}
    mock_response.raise_for_status = MagicMock()

    with patch("app.utils.image_utils.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(ImageDownloadError, match="content-type"):
            await processor.download_image("https://example.com/page.html")
