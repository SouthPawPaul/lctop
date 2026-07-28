import json
import os
from pathlib import Path

def load_config(config_path: str | Path) -> dict:
    """Load configuration from a JSON file."""
    path = Path(config_path).expanduser()
    if path.exists():
        try:
            with path.open("r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}
