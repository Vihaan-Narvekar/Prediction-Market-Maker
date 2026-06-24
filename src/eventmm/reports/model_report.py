from pathlib import Path


def write_model_report(path: Path, metrics: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Model Report", ""]
    lines.extend(f"- {key}: {value}" for key, value in metrics.items())
    path.write_text("\n".join(lines))
    return path
