"""Key-free settings; importing runtime code never reads a credential file.

A03/A15 can inspect chat_key_path and load the selected key privately when
constructing the server-side client. This module never puts keys in os.environ.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


APP_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    root: Path
    data: dict[str, Any]

    def path(self, name: str) -> Path:
        """Resolve a configured distribution path without copying evidence."""
        return (self.root / self.data["paths"][name]).resolve()

    @property
    def secrets_dir(self) -> Path:
        credentials = self.data["chat"]["credentials"]
        location = os.environ.get(credentials["secrets_dir_env"]) or credentials["secrets_dir"]
        return (self.root / location).resolve()

    @property
    def chat_key_path(self) -> Path:
        return self.secrets_dir / self.data["chat"]["credentials"]["key_file"]

    @property
    def chat_key_present(self) -> bool:
        """Presence only, not authentication/format validation; no file read."""
        return self.chat_key_path.is_file() and self.chat_key_path.stat().st_size > 0

    @property
    def chat_unavailable_reason(self) -> str | None:
        if not self.chat_key_present:
            return "Chat unavailable: the configured server key file is missing or empty."
        return None


def load_settings() -> Settings:
    with (APP_ROOT / "ai_settings.yaml").open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return Settings(root=APP_ROOT, data=data)


def prep_cli_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Keep CLI-account authentication separate from any application API key.

    The app key must be read into a backend client only, never the process
    environment. Strip common API-key variables defensively before CLI launch.
    CLI homes/account settings are retained; no authentication files are read.
    """
    return {
        name: value
        for name, value in (os.environ if environ is None else environ).items()
        if not name.upper().endswith(("API_KEY", "API_KEYS", "AUTH_TOKEN"))
        and name.upper() != "OPENAI_ADMIN_KEY"
    }
