from pathlib import Path


def project_root() -> Path:
    """Return the video project root (parent of scripts/)."""
    return Path(__file__).resolve().parents[2]
