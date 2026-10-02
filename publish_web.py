#!/usr/bin/env python3
"""把 screener.py 的输出转换成 GitHub Pages 使用的数据文件。"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
DOCS_DIR = ROOT / "docs"
DATA_DIR = DOCS_DIR / "data"
HISTORY_DIR = DATA_DIR / "history"
SH_TZ = timezone(timedelta(hours=8))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def find_latest_pair() -> tuple[Path, Path, str]:
    screens = sorted(OUTPUT_DIR.glob("screen_*.json"), reverse=True)
    for screen_path in screens:
        stem = screen_path.stem.replace("screen_", "")
        theme_path = OUTPUT_DIR / f"theme_stats_{stem}.json"
        if theme_path.exists():
            return screen_path, theme_path, stem
    raise RuntimeError("没有找到成对的 screen_*.json 和 theme_stats_*.json")


def main() -> int:
    screen_path, theme_path, date_key = find_latest_pair()
    screen = read_json(screen_path)
    themes = read_json(theme_path)
    as_of = screen.get("as_of") or themes.get("as_of") or date_key

    payload = {
        "as_of": as_of,
        "date_key": date_key,
        "generated_at": datetime.now(SH_TZ).isoformat(),
        "model": {
            "count": len(screen.get("results") or []),
            "results": screen.get("results") or [],
            "counters": screen.get("counters") or {},
        },
        "theme": themes,
    }

    history_path = HISTORY_DIR / f"{date_key}.json"
    write_json(history_path, payload)
    write_json(DATA_DIR / "latest.json", payload)

    index_path = HISTORY_DIR / "index.json"
    if index_path.exists():
        try:
            history_index = read_json(index_path)
        except Exception:
            history_index = []
    else:
        history_index = []
    if not isinstance(history_index, list):
        history_index = []

    entry = {
        "date_key": date_key,
        "as_of": as_of,
        "model_count": payload["model"]["count"],
        "stock_count": themes.get("stock_count", 0),
        "top_sector": (themes.get("top_sectors") or [{}])[0].get("name", "-"),
        "top_concept": (themes.get("top_concepts") or [{}])[0].get("name", "-"),
    }
    history_index = [
        item for item in history_index
        if isinstance(item, dict) and item.get("date_key") != date_key
    ]
    history_index.append(entry)
    history_index.sort(key=lambda item: str(item.get("date_key", "")), reverse=True)
    write_json(index_path, history_index)

    print(f"Latest: {DATA_DIR / 'latest.json'}")
    print(f"History: {history_path}")
    print(f"Index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
