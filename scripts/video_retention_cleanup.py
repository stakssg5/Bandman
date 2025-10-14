#!/usr/bin/env python3
"""
video_retention_cleanup.py

Safely remove or move (to trash) video files older than a retention window.
This tool never deletes by identity; it only uses file modification time.

Examples:
  # Dry-run: show files older than 30 days under videos/
  python3 scripts/video_retention_cleanup.py --root videos --older-than 30d --include-exts .mp4,.mov,.avi

  # Actually delete (requires --yes)
  python3 scripts/video_retention_cleanup.py --root videos --older-than 14d --include-exts .mp4 --yes

  # Move to trash directory instead of deleting
  python3 scripts/video_retention_cleanup.py --root videos --older-than 7d --trash-dir .trash/videos

  # Use glob patterns
  python3 scripts/video_retention_cleanup.py --glob 'videos/**/*.mp4' --older-than 90d --yes

  # JSON output for automation
  python3 scripts/video_retention_cleanup.py --root videos --older-than 45d --json

Exit codes:
  0 - success
  1 - invalid args
  2 - runtime error
"""
from __future__ import annotations

import argparse
import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import glob
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

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

# A typical set of video extensions. Users can override with --include-exts
DEFAULT_VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wmv",
    ".flv",
    ".webm",
    ".m4v",
}


@dataclass
class Candidate:
    path: Path
    size_bytes: int
    mtime: datetime  # timezone-aware UTC


@dataclass
class ActionResult:
    path: str
    size_bytes: int
    mtime: str
    action: str  # "dry-run-delete", "dry-run-move", "deleted", "moved", "skipped", "error"
    detail: str


def parse_size_bytes(text: str) -> int:
    s = text.strip().lower()
    m = re.fullmatch(r"(\d+)([kmgt]?b)?", s)
    if not m:
        raise ValueError(f"Invalid size: {text}")
    value = int(m.group(1))
    unit = m.group(2) or "b"
    factor = {
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "tb": 1024**4,
    }[unit]
    return value * factor


def parse_duration(text: str) -> timedelta:
    # Supports e.g. 30d, 12h, 15m, 10w, combined like 1w2d, or just hours like 48h
    s = text.strip().lower()
    if not s:
        raise ValueError("Empty duration")
    pattern = re.compile(r"(\d+)([wdhms])")
    pos = 0
    total = timedelta()
    for m in pattern.finditer(s):
        if m.start() != pos:
            raise ValueError(f"Invalid duration segment at position {pos} in '{text}'")
        value = int(m.group(1))
        unit = m.group(2)
        if unit == "w":
            total += timedelta(weeks=value)
        elif unit == "d":
            total += timedelta(days=value)
        elif unit == "h":
            total += timedelta(hours=value)
        elif unit == "m":
            total += timedelta(minutes=value)
        elif unit == "s":
            total += timedelta(seconds=value)
        pos = m.end()
    if pos != len(s):
        # Allow a plain number meaning days (e.g., "30") for convenience
        if s.isdigit():
            return timedelta(days=int(s))
        raise ValueError(f"Invalid duration tail in '{text}'")
    return total


def parse_exts_arg(arg: Optional[str]) -> Optional[set[str]]:
    if arg is None:
        return None
    arg = arg.strip()
    if arg == "":
        return None
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    result: set[str] = set()
    for p in parts:
        if not p.startswith('.'):  # allow mp4 or .mp4
            p = '.' + p
        result.add(p.lower())
    return result if result else None


def parse_dirs_arg(arg: Optional[str]) -> set[str]:
    if arg is None or arg.strip() == "":
        return set()
    return {p.strip() for p in arg.split(",") if p.strip()}


def is_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
        return True
    except Exception:
        return False


def collect_candidates(
    roots: List[Path],
    globs: List[str],
    include_exts: Optional[set[str]],
    exclude_dirs: set[str],
) -> List[Candidate]:
    seen: set[Path] = set()
    candidates: List[Candidate] = []

    def try_add(path: Path) -> None:
        if path in seen:
            return
        if not path.is_file():
            return
        if include_exts is not None and path.suffix.lower() not in include_exts:
            return
        try:
            st = path.stat()
        except OSError:
            return
        candidates.append(
            Candidate(
                path=path,
                size_bytes=st.st_size,
                mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            )
        )
        seen.add(path)

    # From glob patterns
    for pattern in globs:
        for match in glob.glob(pattern, recursive=True):
            try_add(Path(match))

    # From roots walk
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excludes
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            for filename in filenames:
                try_add(Path(dirpath) / filename)

    return candidates


def ensure_trash_destination(trash_dir: Path, roots: List[Path], file_path: Path) -> Path:
    # Try to preserve relative path under the first matching root
    for root in roots:
        if is_within(root, file_path):
            rel = file_path.relative_to(root)
            dest = trash_dir / root.name / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            return dest
    # Fallback: flat under trash with original name
    dest = trash_dir / file_path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def perform_cleanup(
    candidates: List[Candidate],
    older_than: timedelta,
    dry_run: bool,
    confirm_yes: bool,
    move_to: Optional[Path],
    roots: List[Path],
) -> Tuple[List[ActionResult], int, int]:
    now = datetime.now(timezone.utc)
    threshold = now - older_than
    results: List[ActionResult] = []
    total_files = 0
    total_bytes = 0

    for c in candidates:
        if c.mtime > threshold:
            continue
        total_files += 1
        total_bytes += c.size_bytes
        try:
            if move_to is not None:
                dest = ensure_trash_destination(move_to, roots, c.path)
                if dry_run or not confirm_yes:
                    results.append(
                        ActionResult(
                            path=str(c.path),
                            size_bytes=c.size_bytes,
                            mtime=c.mtime.isoformat(),
                            action="dry-run-move",
                            detail=f"-> {dest}",
                        )
                    )
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(c.path), str(dest))
                    results.append(
                        ActionResult(
                            path=str(c.path),
                            size_bytes=c.size_bytes,
                            mtime=c.mtime.isoformat(),
                            action="moved",
                            detail=f"-> {dest}",
                        )
                    )
            else:
                if dry_run or not confirm_yes:
                    results.append(
                        ActionResult(
                            path=str(c.path),
                            size_bytes=c.size_bytes,
                            mtime=c.mtime.isoformat(),
                            action="dry-run-delete",
                            detail="",
                        )
                    )
                else:
                    c.path.unlink(missing_ok=True)
                    results.append(
                        ActionResult(
                            path=str(c.path),
                            size_bytes=c.size_bytes,
                            mtime=c.mtime.isoformat(),
                            action="deleted",
                            detail="",
                        )
                    )
        except Exception as e:
            results.append(
                ActionResult(
                    path=str(c.path),
                    size_bytes=c.size_bytes,
                    mtime=c.mtime.isoformat(),
                    action="error",
                    detail=str(e),
                )
            )

    return results, total_files, total_bytes


def format_human(results: List[ActionResult], total_files: int, total_bytes: int) -> str:
    def fmt_size(n: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if n < 1024 or unit == "TB":
                return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
            n /= 1024
        return f"{n:.1f} TB"

    lines: List[str] = []
    for r in results:
        if r.action.startswith("dry-run"):
            prefix = "PLAN"
        elif r.action in ("deleted", "moved"):
            prefix = "DONE"
        elif r.action == "skipped":
            prefix = "SKIP"
        else:
            prefix = "ERR"
        mt = r.mtime.replace("T", " ")
        detail = f" {r.detail}" if r.detail else ""
        lines.append(f"{prefix} {mt} {r.action:>14} {fmt_size(r.size_bytes):>10} {r.path}{detail}")

    lines.append("")
    lines.append(f"Total matched files: {total_files}")
    lines.append(f"Total matched size:  {fmt_size(total_bytes)}")
    return "\n".join(lines)


def format_json(results: List[ActionResult], total_files: int, total_bytes: int) -> str:
    payload = {
        "summary": {
            "matched_files": total_files,
            "matched_bytes": total_bytes,
        },
        "results": [dataclasses.asdict(r) for r in results],
    }
    return json.dumps(payload, indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Delete or move videos older than a retention window (by mtime)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--root", action="append", default=[], help="Root directory to scan (can be repeated)")
    parser.add_argument("--glob", dest="globs", action="append", default=[], help="Glob pattern(s) to match files, e.g. 'videos/**/*.mp4'")
    parser.add_argument("--older-than", default="30d", help="Retention age threshold, e.g. 30d, 12h, 1w2d")
    parser.add_argument("--include-exts", default=",".join(sorted(DEFAULT_VIDEO_EXTS)), help="Comma-separated list of allowed extensions; empty to allow all")
    parser.add_argument("--exclude-dirs", default=",".join(sorted(DEFAULT_EXCLUDE_DIRS)), help="Comma-separated directory names to exclude")
    parser.add_argument("--min-size", default="0b", help="Minimum file size to consider (e.g., 10MB, 500KB)")
    parser.add_argument("--trash-dir", default=None, help="If set, move files here instead of deleting")
    parser.add_argument("--yes", action="store_true", help="Confirm performing actions (otherwise dry-run)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of human-readable text")

    args = parser.parse_args(argv)

    try:
        older_than = parse_duration(args.older_than)
    except Exception as e:
        print(f"Invalid --older-than: {e}", file=sys.stderr)
        return 1

    include_exts = parse_exts_arg(args.include_exts)
    exclude_dirs = DEFAULT_EXCLUDE_DIRS | parse_dirs_arg(args.exclude_dirs)
    try:
        min_size_bytes = parse_size_bytes(args.min_size)
    except Exception as e:
        print(f"Invalid --min-size: {e}", file=sys.stderr)
        return 1

    roots: List[Path] = [Path(r).resolve() for r in (args.root or [])]
    if not roots and not args.globs:
        # Default root to current directory if nothing specified
        roots = [Path.cwd()]

    # Validate roots exist
    for root in roots:
        if not root.exists() or not root.is_dir():
            print(f"Root does not exist or is not a directory: {root}", file=sys.stderr)
            return 1

    # If trash-dir specified, ensure it's a directory (create if needed)
    trash_dir: Optional[Path] = None
    if args.trash_dir:
        trash_dir = Path(args.trash_dir).resolve()
        try:
            trash_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Cannot create trash dir '{trash_dir}': {e}", file=sys.stderr)
            return 2

    # Collect candidates
    candidates = collect_candidates(roots=roots, globs=args.globs, include_exts=include_exts, exclude_dirs=exclude_dirs)

    # Filter by size
    candidates = [c for c in candidates if c.size_bytes >= min_size_bytes]

    # Execute (dry-run unless --yes)
    dry_run = not args.yes
    try:
        results, total_files, total_bytes = perform_cleanup(
            candidates=candidates,
            older_than=older_than,
            dry_run=dry_run,
            confirm_yes=bool(args.yes),
            move_to=trash_dir,
            roots=roots,
        )
    except Exception as e:
        print(f"Runtime error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(format_json(results, total_files, total_bytes))
    else:
        print(format_human(results, total_files, total_bytes))
        if dry_run:
            print("\nNOTE: Dry-run only. Pass --yes to perform actions.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
