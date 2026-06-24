from pathlib import Path


def write_backtest_report(path: Path, metrics: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Backtest Report", ""]
    lines.extend(f"- {key}: {value}" for key, value in metrics.items())
    path.write_text("\n".join(lines))
    return path
