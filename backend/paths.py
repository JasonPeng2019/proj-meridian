"""Every writable project path is rooted here, including child-process state."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("MERIDIAN_ROOT", Path(__file__).resolve().parents[1])).resolve()
CORPUS = ROOT / "project-meridian_Avathon" / "project-meridian"
GENERATED = ROOT / "generated"
DECISIONS = ROOT / "decisions"

def inside(path: str | Path) -> Path:
    value = Path(path)
    value = (ROOT / value).resolve() if not value.is_absolute() else value.resolve()
    if not value.is_relative_to(ROOT):
        raise ValueError("Project path escapes the Avathon workspace")
    return value

def configure_environment() -> None:
    paths = {
        "TEMP": ".tmp", "TMP": ".tmp", "TMPDIR": ".tmp",
        "UV_CACHE_DIR": ".cache/uv", "PIP_CACHE_DIR": ".cache/pip",
        "UV_PYTHON_INSTALL_DIR": ".runtime/python",
        "npm_config_cache": ".cache/npm", "PLAYWRIGHT_BROWSERS_PATH": ".cache/playwright",
        "CODEX_HOME": ".runtime/codex", "CLAUDE_CONFIG_DIR": ".runtime/claude",
        "GH_CONFIG_DIR": ".runtime/gh",
    }
    for key, relative in paths.items():
        target = inside(relative)
        target.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(target)
    os.environ["DISABLE_AUTOUPDATER"] = "1"
