"""Runtime configuration loaded from environment variables (never hardcoded secrets)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

EXTRACTOR_VERSION = "rules-1.0.0"
DETECTOR_VERSION = "analysis-1.0.0"

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_DIR = _BACKEND_DIR.parent


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing env vars take precedence."""
    for candidate in (_REPO_DIR / ".env", _BACKEND_DIR / ".env"):
        if not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("MEDTRACE_DATA_DIR", str(_REPO_DIR / "runtime-data"))).resolve())
    admin_username: str = field(default_factory=lambda: os.environ.get("MEDTRACE_ADMIN_USERNAME", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ.get("MEDTRACE_ADMIN_PASSWORD", ""))
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("MEDTRACE_MAX_UPLOAD_MB", "15")))
    max_pdf_pages: int = field(default_factory=lambda: int(os.environ.get("MEDTRACE_MAX_PDF_PAGES", "60")))
    session_hours: int = field(default_factory=lambda: int(os.environ.get("MEDTRACE_SESSION_HOURS", "8")))
    cookie_secure: bool = field(default_factory=lambda: _bool("MEDTRACE_COOKIE_SECURE", False))
    cors_origins: list[str] = field(default_factory=lambda: [o.strip() for o in os.environ.get(
        "MEDTRACE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()])
    ocr_engine: str = field(default_factory=lambda: os.environ.get("MEDTRACE_OCR_ENGINE", "rapidocr"))
    # A page whose native text layer has fewer characters than this is treated as scanned.
    native_text_min_chars: int = 25
    login_max_failures: int = 5
    login_lockout_seconds: int = 300

    @property
    def db_path(self) -> Path:
        return self.data_dir / "medtrace.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def override_settings(s: Settings) -> None:
    """Used by tests to point the app at an isolated temporary data directory."""
    global _settings
    s.ensure_dirs()
    _settings = s
