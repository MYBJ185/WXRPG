from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
WORLD_DIR = DATA_DIR / "world"
STORY_DIR = DATA_DIR / "story"
OUTPUT_STYLE_REGEX = STORY_DIR / "output_style.regex"
SAVE_DIR = ROOT_DIR / "saves"
CHROMA_DIR = ROOT_DIR / "storage" / "chroma"

load_dotenv(ROOT_DIR / ".env")


class Settings(BaseSettings):
    longcat_api_key: str | None = Field(default=None, alias="LONGCAT_API_KEY")
    longcat_model: str = Field(default="longcat-flash-chat", alias="LONGCAT_MODEL")
    longcat_base_url: str = Field(
        default="https://api.longcat.chat/openai/v1",
        alias="LONGCAT_BASE_URL",
    )
    jianghu_use_longcat: bool = Field(default=True, alias="JIANGHU_USE_LONGCAT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()
