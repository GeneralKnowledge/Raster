"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the raster-to-svg service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="raster-to-svg", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    max_file_size_mb: float = Field(default=20.0, alias="MAX_FILE_SIZE_MB")
    max_image_width: int = Field(default=10000, alias="MAX_IMAGE_WIDTH")
    max_image_height: int = Field(default=10000, alias="MAX_IMAGE_HEIGHT")
    max_image_pixels: int = Field(default=50_000_000, alias="MAX_IMAGE_PIXELS")
    max_concurrent_jobs: int = Field(default=2, alias="MAX_CONCURRENT_JOBS")
    api_key_required: bool = Field(default=False, alias="API_KEY_REQUIRED")
    api_key: str = Field(default="", alias="API_KEY")
    allow_origins: str = Field(default="*", alias="ALLOW_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # Pillow enhance mode: auto (on for photo), always, or never.
    # Accepts true/false aliases. Per-request pillow_enhance overrides this.
    pillow_enhance: str = Field(default="auto", alias="PILLOW_ENHANCE")

    @property
    def max_file_size_bytes(self) -> int:
        return int(self.max_file_size_mb * 1024 * 1024)

    @property
    def cors_origins(self) -> list[str]:
        raw = self.allow_origins.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
