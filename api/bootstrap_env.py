"""
Load root `.env` into `os.environ` for local dev (Vercel injects env vars; dotenv does not override them).

Call via `api` package import — see `api/__init__.py`.
"""

from __future__ import annotations

from pathlib import Path


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False)
