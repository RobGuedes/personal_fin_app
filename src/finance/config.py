"""Settings loaded from .env (never log secret values)."""

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, SecretStr, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CONFIG_DIR = PROJECT_ROOT / "config"


def example_of(path: Path) -> Path:
    """config/rules.yaml -> config/rules.example.yaml (the committed template of a gitignored config file)."""
    return path.with_name(f"{path.stem}.example{path.suffix}")


def readable_config(path: Path) -> Path:
    """The file to read for `path`: itself if it exists, else its committed `.example` template."""
    if not path.exists() and example_of(path).exists():
        return example_of(path)
    return path


def writable_config(path: Path) -> Path:
    """`path`, created from its `.example` template first if it does not exist yet (never edit the template)."""
    if not path.exists() and example_of(path).exists():
        shutil.copyfile(example_of(path), path)
    return path


class Settings(BaseModel):
    pluggy_client_id: str
    pluggy_client_secret: SecretStr
    pluggy_item_ids: list[str] = []
    my_cpf: str = ""
    my_name: str = ""
    pluggy_base_url: str = "https://api.pluggy.ai"
    binance_api_key: str = ""
    binance_api_secret: SecretStr = SecretStr("")
    binance_base_url: str = "https://api.binance.com"

    @field_validator("pluggy_item_ids", mode="before")
    @classmethod
    def _split_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        pluggy_client_id=os.environ.get("PLUGGY_CLIENT_ID", ""),
        pluggy_client_secret=os.environ.get("PLUGGY_CLIENT_SECRET", ""),
        pluggy_item_ids=os.environ.get("PLUGGY_ITEM_IDS", ""),
        my_cpf=os.environ.get("MY_CPF", ""),
        my_name=os.environ.get("MY_NAME", ""),
        binance_api_key=os.environ.get("BINANCE_API_KEY", ""),
        binance_api_secret=os.environ.get("BINANCE_API_SECRET", ""),
    )
