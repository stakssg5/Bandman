#!/usr/bin/env python3
"""
camera_live_view.py

Safe camera live viewer. Looks up a stream URL from a name via config or a
parameterized SQLite query, then optionally launches an external player (ffplay)
or prints the URL. No face/identity recognition is performed.

Examples:
  # Using a simple JSON config mapping names to URLs
  python3 scripts/camera_live_view.py --name "Alice" --config configs/cameras.json --print
  python3 scripts/camera_live_view.py --name "Lobby" --config configs/cameras.json --open

  # Using SQLite with a parameterized query (':name' parameter)
  python3 scripts/camera_live_view.py --name Bob \
      --sqlite data/cameras.db \
      --query "SELECT stream_url FROM cameras WHERE person_name = :name LIMIT 1" \
      --open

  # Direct URL (no lookup), just open
  python3 scripts/camera_live_view.py --url rtsp://cam-host/stream --open

Notes:
- '--open' requires ffplay (from ffmpeg) installed and available in PATH.
- '--query' must be a single-row, single-column SELECT returning the URL.
- This tool does NOT identify anyone on camera; it only retrieves configured URLs.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Dict, Optional, Sequence

try:
    import yaml  # type: ignore
except Exception:  # optional
    yaml = None  # type: ignore


def load_mapping_from_config(config_path: Path) -> Dict[str, str]:
    suffix = config_path.suffix.lower()
    if not config_path.exists() or not config_path.is_file():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()

    data: Any
    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("PyYAML not installed; install pyyaml or use JSON config")
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)

    # Accept a few flexible shapes
    mapping: Dict[str, str] = {}

    if isinstance(data, dict):
        # Flat mapping {name: url}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str):
                mapping[k] = v
        # Nested common shapes
        if not mapping:
            # {"cameras": {name: url}}
            cameras = data.get("cameras") if isinstance(data, dict) else None
            if isinstance(cameras, dict):
                for k, v in cameras.items():
                    if isinstance(k, str) and isinstance(v, str):
                        mapping[k] = v
            # {"people": [{"name":..., "url":...}]}
            people = data.get("people") if isinstance(data, dict) else None
            if isinstance(people, list):
                for item in people:
                    if isinstance(item, dict):
                        name = item.get("name")
                        url = item.get("url")
                        if isinstance(name, str) and isinstance(url, str):
                            mapping[name] = url
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = item.get("name")
                url = item.get("url")
                if isinstance(name, str) and isinstance(url, str):
                    mapping[name] = url

    if not mapping:
        raise ValueError("Could not parse a name->url mapping from config")

    return mapping


def lookup_url_from_config(name: str, config_path: Path, contains: bool, case_insensitive: bool) -> str:
    mapping = load_mapping_from_config(config_path)
    candidates: Dict[str, str] = {}

    if case_insensitive:
        name_lc = name.lower()
        for k, v in mapping.items():
            key = k.lower()
            if contains:
                if name_lc in key:
                    candidates[k] = v
            else:
                if key == name_lc:
                    candidates[k] = v
    else:
        for k, v in mapping.items():
            if contains:
                if name in k:
                    candidates[k] = v
            else:
                if k == name:
                    candidates[k] = v

    if not candidates:
        raise LookupError(f"Name '{name}' not found in config {config_path}")

    # If multiple matches with contains, prefer exact (case-insensitive) equality if present
    if len(candidates) > 1 and contains:
        exact = [k for k in candidates if k.lower() == name.lower()]
        if exact:
            return candidates[exact[0]]
        # Otherwise choose the shortest key as heuristic
        return candidates[sorted(candidates, key=len)[0]]

    # Single match
    return next(iter(candidates.values()))


def lookup_url_from_sqlite(name: str, sqlite_path: Path, query: str) -> str:
    if not sqlite_path.exists() or not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")
    if "select" not in query.lower():
        raise ValueError("--query must be a SELECT statement returning a single URL")

    conn = sqlite3.connect(str(sqlite_path))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(query, {"name": name})
        row = cur.fetchone()
        if row is None:
            raise LookupError("No rows returned for the given name")
        # Accept first column
        url = row[0]
        if not isinstance(url, str):
            raise TypeError("Query did not return a string URL in the first column")
        return url
    finally:
        conn.close()


def open_with_ffplay(url: str, extra_args: Sequence[str]) -> int:
    ffplay_path = shutil.which("ffplay")
    if ffplay_path is None:
        raise RuntimeError("ffplay not found in PATH. Install ffmpeg or omit --open to print URL.")
    cmd = [ffplay_path, "-nostats", "-loglevel", "error", url]
    if extra_args:
        cmd.extend(extra_args)
    # Launch ffplay and wait for its exit; the user can close the window to exit.
    return subprocess.call(cmd)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a camera stream URL by name (config/SQLite) or direct URL, then optionally open with ffplay",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", help="Name to look up in config/DB (e.g., person, location, camera label)")
    group.add_argument("--url", help="Direct camera stream URL (e.g., rtsp://...) to open/print")

    parser.add_argument("--config", help="Path to JSON/YAML config containing name->url mapping")
    parser.add_argument("--sqlite", help="Path to SQLite database for lookup")
    parser.add_argument("--query", help="Parameterized SELECT SQL using :name to return one URL")

    parser.add_argument("--contains", action="store_true", help="Allow substring matches when using --config lookups")
    parser.add_argument("--case-insensitive", action="store_true", help="Case-insensitive name matching for --config lookups")

    parser.add_argument("--open", action="store_true", help="Open the resolved URL with ffplay")
    parser.add_argument("--ffplay-arg", action="append", default=[], help="Extra args to pass to ffplay (repeatable)")
    parser.add_argument("--print", dest="do_print", action="store_true", help="Print the resolved URL to stdout")
    parser.add_argument("--json", action="store_true", help="Output JSON with the resolved URL and launch status")

    args = parser.parse_args(argv)

    resolved_url: Optional[str] = None

    try:
        if args.url:
            resolved_url = args.url
        else:
            # Using name-based lookup
            if args.config:
                resolved_url = lookup_url_from_config(
                    name=args.name,
                    config_path=Path(args.config).resolve(),
                    contains=bool(args.contains),
                    case_insensitive=bool(args.case_insensitive),
                )
            elif args.sqlite and args.query:
                resolved_url = lookup_url_from_sqlite(
                    name=args.name,
                    sqlite_path=Path(args.sqlite).resolve(),
                    query=args.query,
                )
            else:
                print("Provide either --config or (--sqlite and --query) when using --name", file=sys.stderr)
                return 1
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    # Output / open
    launch_status = None
    if args.open:
        try:
            rc = open_with_ffplay(resolved_url, args.ffplay_arg)
            launch_status = {"launched": True, "return_code": rc}
        except Exception as e:
            if args.json:
                print(json.dumps({"ok": False, "url": resolved_url, "error": str(e)}))
            else:
                print(f"Error launching ffplay: {e}", file=sys.stderr)
            return 1

    if args.json:
        print(json.dumps({"ok": True, "url": resolved_url, "launched": bool(args.open), "ffplay_return_code": (launch_status or {}).get("return_code")}))
    else:
        if args.do_print or not args.open:
            print(resolved_url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
