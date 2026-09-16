"""Configuration manager for WebAssetify.

Loads settings from environment variables and provides fallback defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()


@dataclass(frozen=True)
class Config:
    """Application configuration settings."""

    # Telegram Bot
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Google Drive
    gdrive_parent_folder_id: str = os.getenv("GDRIVE_PARENT_FOLDER_ID", "")
    gdrive_service_account_json: str = os.getenv("GDRIVE_SERVICE_ACCOUNT_JSON", "")

    # Server Keep-Alive
    port: int = int(os.getenv("PORT", "8080"))

    # Media Optimization
    max_video_height: int = int(os.getenv("MAX_VIDEO_HEIGHT", "720"))
    webp_quality: int = int(os.getenv("WEBP_QUALITY", "80"))
    max_image_dimension: int = int(os.getenv("MAX_IMAGE_DIMENSION", "2560"))

    # Scratch Directory
    temp_dir: Path = Path(os.getenv("TEMP_DIR", "/tmp/webassetify"))

    def validate(self, check_secrets: bool = True) -> list[str]:
        """Validate the configuration and return a list of error messages."""
        errors: list[str] = []

        if check_secrets:
            if not self.telegram_bot_token:
                errors.append("TELEGRAM_BOT_TOKEN is required.")
            if not self.gdrive_parent_folder_id:
                errors.append("GDRIVE_PARENT_FOLDER_ID is required.")
            if not self.gdrive_service_account_json:
                errors.append("GDRIVE_SERVICE_ACCOUNT_JSON is required.")

        if self.port <= 0 or self.port > 65535:
            errors.append(f"Invalid PORT: {self.port}. Must be between 1 and 65535.")

        if self.max_video_height <= 0:
            errors.append(
                f"Invalid MAX_VIDEO_HEIGHT: {self.max_video_height}. Must be positive."
            )

        if not (1 <= self.webp_quality <= 100):
            errors.append(
                f"Invalid WEBP_QUALITY: {self.webp_quality}. Must be between 1 and 100."
            )

        if self.max_image_dimension <= 0:
            errors.append(
                f"Invalid MAX_IMAGE_DIMENSION: {self.max_image_dimension}. Must be positive."
            )

        return errors

    def to_safe_dict(self) -> dict[str, str | int]:
        """Return configuration as a dictionary with masked sensitive values."""
        def mask(val: str) -> str:
            if not val:
                return "<not set>"
            if len(val) <= 8:
                return "***"
            return f"{val[:4]}...{val[-4:]}"

        return {
            "telegram_bot_token": mask(self.telegram_bot_token),
            "gdrive_parent_folder_id": mask(self.gdrive_parent_folder_id),
            "gdrive_service_account_json": "<configured>" if self.gdrive_service_account_json else "<not set>",
            "port": self.port,
            "max_video_height": self.max_video_height,
            "webp_quality": self.webp_quality,
            "max_image_dimension": self.max_image_dimension,
            "temp_dir": str(self.temp_dir),
        }


# Global config instance
config = Config()
