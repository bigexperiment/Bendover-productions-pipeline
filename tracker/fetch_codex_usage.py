"""Shim → scripts/07_credits/fetch_codex_usage.py"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent.parent / "scripts/07_credits/fetch_codex_usage.py"), run_name="__main__")
