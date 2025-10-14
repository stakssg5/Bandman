#!/usr/bin/env python3
"""
find_numbers_recent.py

Search text files recursively for lines containing numbers, then return the most
recent matches sorted by timestamps embedded in the line when available, or by
file modification time as a fallback.

Examples:
  python scripts/find_numbers_recent.py --root . --top 30 --context 1
  python scripts/find_numbers_recent.py --root logs --pattern "USD\s*[-+]?[0-9,.]+" --sort auto -C 2
  python scripts/find_numbers_recent.py --root data --include-exts .txt,.log --json --top 50

Exit codes:
  0 - success, results may be empty
  1 - generic failure
"""
from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple


DEFAULT_NUMERIC_PATTERN = r"(?<!\w)(?:-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+\.\d+|-?\d+)(?!\w)"
# Common directories to skip when walking
DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".next",
    ".cache",
    ".idea",
    ".vscode",
}
# Reasonable default set of text file extensions; scanning is still text-based and safe
DEFAULT_INCLUDE_EXTS = {
    ".txt",
    ".log",
    ".md",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".conf",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rb",
    ".sh",
}

ISO_DATE_RE = re.compile(
    # Examples: 2024-07-31, 2024-07-31T13:45:22, 2024-07-31 13:45:22.123Z, 2024-07-31T13:45:22+02:00
    r"\b(\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?)\b"
)
# 12/31/2024 or 31/12/2024, will interpret as MDY by default unless --dmy
SLASH_DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})(?:[ T](\d{2}:\d{2}:\d{2}))?\b")
DASH_DATE_RE = re.compile(r"\b(\d{4}/\d{2}/\d{2})(?:[ T](\d{2}:\d{2}:\d{2}))?\b")


@dataclass
class MatchEntry:
    file_path: Path
    line_number: int
    line_text: str
    matched_numbers: List[str]
    when: datetime
    when_source: str  # 'line' or 'mtime'
    file_mtime: datetime


def is_probably_text(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
            if not chunk:
                return True
            # Heuristic: binary files often contain NUL bytes
            if b"\x00" in chunk:
                return False
            # If most bytes are ASCII or common UTF-8, treat as text
            text_bytes = sum(1 for b in chunk if 9 <= b <= 13 or 32 <= b <= 126)
            return text_bytes / max(1, len(chunk)) > 0.85
    except OSError:
        return False


def parse_iso_datetime(text: str) -> Optional[datetime]:
    try:
        # Handle trailing Z for UTC
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        # Support timezone without colon (e.g., +0000)
        # datetime.fromisoformat supports both in Python 3.11+
        dt = datetime.fromisoformat(text)
        # Normalize to UTC for consistent ordering
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def try_parse_datetime_candidates(line: str, prefer_dmy: bool) -> Optional[datetime]:
    # Try ISO first
    for m in ISO_DATE_RE.finditer(line):
        dt = parse_iso_datetime(m.group(1))
        if dt is not None:
            return dt

    # Try YYYY/MM/DD
    for m in DASH_DATE_RE.finditer(line):
        date_part = m.group(1)
        time_part = m.group(2)
        try:
            if time_part:
                dt = datetime.strptime(f"{date_part} {time_part}", "%Y/%m/%d %H:%M:%S")
            else:
                dt = datetime.strptime(date_part, "%Y/%m/%d")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    # Try DD/MM/YYYY or MM/DD/YYYY depending on preference
    for m in SLASH_DATE_RE.finditer(line):
        date_part = m.group(1)
        time_part = m.group(2)
        fmt = "%d/%m/%Y" if prefer_dmy else "%m/%d/%Y"
        try:
            if time_part:
                dt = datetime.strptime(f"{date_part} {time_part}", f"{fmt} %H:%M:%S")
            else:
                dt = datetime.strptime(date_part, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            # Try the other interpretation as a fallback
            alt_fmt = "%m/%d/%Y" if prefer_dmy else "%d/%m/%Y"
            try:
                if time_part:
                    dt = datetime.strptime(f"{date_part} {time_part}", f"{alt_fmt} %H:%M:%S")
                else:
                    dt = datetime.strptime(date_part, alt_fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

    return None


def walk_files(root: Path, include_exts: Optional[set[str]], exclude_dirs: set[str], follow_symlinks: bool) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        # Prune excluded directories in-place for efficiency
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for filename in filenames:
            path = Path(dirpath) / filename
            if include_exts is not None and path.suffix.lower() not in include_exts:
                continue
            yield path


def find_matches_in_file(
    path: Path,
    number_re: re.Pattern[str],
    sort_mode: str,
    prefer_dmy: bool,
    context: int,
    max_file_size: int,
) -> List[MatchEntry]:
    try:
        stat = path.stat()
        if stat.st_size > max_file_size:
            return []
    except OSError:
        return []

    if not is_probably_text(path):
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return []

    file_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    results: List[MatchEntry] = []
    for idx, line in enumerate(lines):
        matches = number_re.findall(line)
        if not matches:
            continue

        when_source = "mtime"
        when_dt: datetime = file_mtime
        if sort_mode in ("auto", "line"):
            dt = try_parse_datetime_candidates(line, prefer_dmy)
            if dt is not None:
                when_dt = dt
                when_source = "line"

        # Collapse whitespace for cleaner output
        line_text = line.rstrip("\n")
        results.append(
            MatchEntry(
                file_path=path,
                line_number=idx + 1,
                line_text=line_text,
                matched_numbers=matches if isinstance(matches, list) else [str(matches)],
                when=when_dt,
                when_source=when_source,
                file_mtime=file_mtime,
            )
        )

    return results


def format_human(entries: List[MatchEntry], context: int, all_lines_by_file: dict[Path, List[str]]) -> str:
    out_lines: List[str] = []
    for e in entries:
        ts_display = e.when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        header = f"{ts_display} [{e.when_source}] {e.file_path}:{e.line_number}"
        out_lines.append(header)
        # Context block
        if context > 0:
            lines = all_lines_by_file.get(e.file_path)
            if lines is None:
                try:
                    with open(e.file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        all_lines_by_file[e.file_path] = lines
                except OSError:
                    lines = []
            start = max(0, e.line_number - 1 - context)
            end = min(len(lines), e.line_number - 1 + context + 1)
            for i in range(start, end):
                prefix = ">" if i == e.line_number - 1 else "-"
                out_lines.append(f"  {prefix} {i+1:>6}: {lines[i].rstrip()}" )
        else:
            out_lines.append(f"  > {e.line_number:>6}: {e.line_text}")
        out_lines.append("")
    return "\n".join(out_lines)


def format_json(entries: List[MatchEntry]) -> str:
    def encode_dt(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).isoformat()

    payload = [
        {
            "path": str(e.file_path),
            "line_number": e.line_number,
            "line": e.line_text,
            "numbers": e.matched_numbers,
            "timestamp": encode_dt(e.when),
            "timestamp_source": e.when_source,
            "file_mtime": encode_dt(e.file_mtime),
        }
        for e in entries
    ]
    return json.dumps(payload, indent=2)


def parse_exts_arg(arg: Optional[str]) -> Optional[set[str]]:
    if arg is None or arg.strip() == "":
        return None
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    exts: set[str] = set()
    for p in parts:
        if not p.startswith('.'):
            p = '.' + p
        exts.add(p.lower())
    return exts if exts else None


def parse_dirs_arg(arg: Optional[str]) -> set[str]:
    if arg is None or arg.strip() == "":
        return set()
    return {p.strip() for p in arg.split(",") if p.strip()}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Search for numbers in text files and show the most recent lines",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--root", default=str(Path.cwd()), help="Root directory to scan")
    parser.add_argument("--pattern", default=DEFAULT_NUMERIC_PATTERN, help="Regex pattern to match numbers")
    parser.add_argument("--sort", choices=["auto", "line", "mtime"], default="auto", help="Recency source: prefer line timestamps or use file mtime")
    parser.add_argument("--dmy", action="store_true", help="Interpret slash dates as DD/MM/YYYY instead of MM/DD/YYYY")
    parser.add_argument("--top", type=int, default=20, help="Show only the top N most recent matches")
    parser.add_argument("-C", "--context", type=int, default=1, help="Number of context lines before/after each match")
    parser.add_argument("--include-exts", default=",".join(sorted(DEFAULT_INCLUDE_EXTS)), help="Comma-separated list of file extensions to include; empty to include all")
    parser.add_argument("--exclude-dirs", default=",".join(sorted(DEFAULT_EXCLUDE_DIRS)), help="Comma-separated directory names to exclude during traversal")
    parser.add_argument("--max-file-size", type=int, default=2_000_000, help="Maximum file size (bytes) to scan")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks when walking the tree")
    parser.add_argument("--ignore-case", action="store_true", help="Case-insensitive matching for the pattern")
    parser.add_argument("--json", action="store_true", help="Output results as JSON instead of human-readable text")

    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print(f"Root directory does not exist or is not a directory: {root}", file=sys.stderr)
        return 1

    include_exts = parse_exts_arg(args.include_exts)
    if include_exts is None:
        include_exts = None  # Scan all file extensions when None
    exclude_dirs = DEFAULT_EXCLUDE_DIRS | parse_dirs_arg(args.exclude_dirs)

    flags = re.IGNORECASE if args.ignore_case else 0
    try:
        number_re = re.compile(args.pattern, flags)
    except re.error as e:
        print(f"Invalid regex pattern: {e}", file=sys.stderr)
        return 1

    all_matches: List[MatchEntry] = []
    for path in walk_files(root, include_exts, exclude_dirs, args.follow_symlinks):
        file_matches = find_matches_in_file(
            path=path,
            number_re=number_re,
            sort_mode=args.sort,
            prefer_dmy=bool(args.dmy),
            context=args.context,
            max_file_size=args.max_file_size,
        )
        if file_matches:
            all_matches.extend(file_matches)

    if not all_matches:
        if args.json:
            print("[]")
        else:
            print("No matches found.")
        return 0

    # Sort by recency descending
    all_matches.sort(key=lambda e: e.when, reverse=True)

    # Keep only top N
    if args.top is not None and args.top > 0:
        all_matches = all_matches[: args.top]

    if args.json:
        print(format_json(all_matches))
    else:
        # Build context cache for efficient context rendering across files
        all_lines_by_file: dict[Path, List[str]] = {}
        print(format_human(all_matches, context=args.context, all_lines_by_file=all_lines_by_file))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
