"""Custom exceptions for the platform adapter layer.

These exceptions are **internal** — they are caught inside synchronous helper
methods (e.g. ``_sync_create_campaign``) and converted to
``ExecutionResult(success=False)`` at the public async boundary.  They should
never escape into calling code.
"""

from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    """Base exception for all platform-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = details or {}


class ImageDownloadError(PlatformError):
    """Raised when an image cannot be downloaded from the provided URL."""


class ImageValidationError(PlatformError):
    """Raised when an image fails validation (corrupt, wrong format, too small, etc.)."""


class ImageUploadError(PlatformError):
    """Raised when an image upload to the ad platform fails."""


class CreativeCreationError(PlatformError):
    """Raised when AdCreative or Ad object creation fails on the platform."""
