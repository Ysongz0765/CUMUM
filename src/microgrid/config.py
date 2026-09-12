from pathlib import Path
import yaml

def load_config(path: str | Path | None = None) -> dict:
    path = Path(path or Path(__file__).parents[2] / "configs" / "config.yaml")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
