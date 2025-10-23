#!/usr/bin/env python3
import argparse
import gzip
import io
import os
import re
import sys
import zipfile
from collections import deque
from typing import Iterable, Iterator, List, Optional, Tuple

TEXT_EXTENSIONS = {
    ".log", ".txt", ".json", ".jsonl", ".ndjson", ".csv", ".tsv",
}
COMPRESSED_EXTENSIONS = {".gz", ".zip"}
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100MB safety cap

DEFAULT_PATTERNS = [
    r"\bcash[-_ ]?out(s|ed|ing)?\b",
    r"\bwithdraw(al|s|n|ing|ed)?\b",
    r"\bpayout(s|ed|ing)?\b",
    r"\bdump(s|ed|ing)?\b",
    r"\blog[-_ ]?dump(s|ed|ing)?\b",
]

class Match:
    def __init__(self, file_path: str, line_no: int, line: str, pattern: str):
        self.file_path = file_path
        self.line_no = line_no
        self.line = line.rstrip("\n")
        self.pattern = pattern

    def __str__(self) -> str:
        return f"{self.file_path}:{self.line_no}: {self.line}"


def is_binary_sniff(sample: bytes) -> bool:
    # Heuristic: presence of NUL or very high non-text ratio
    if b"\x00" in sample:
        return True
    # If many bytes are outside typical text range, assume binary
    text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(32, 127)))
    non_text = sum(1 for b in sample if b not in text_chars)
    return non_text / max(1, len(sample)) > 0.30


def should_scan_file(path: str, include_all_text_like: bool) -> bool:
    lower = path.lower()
    _, ext = os.path.splitext(lower)
    if ext in COMPRESSED_EXTENSIONS:
        return True
    if ext in TEXT_EXTENSIONS:
        return True
    if include_all_text_like:
        try:
            size = os.path.getsize(path)
            if size == 0 or size > DEFAULT_MAX_FILE_BYTES:
                return False
            with open(path, "rb") as f:
                sample = f.read(4096)
            return not is_binary_sniff(sample)
        except Exception:
            return False
    return False


def iter_text_lines(path: str) -> Iterator[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def iter_gz_lines(path: str) -> Iterator[str]:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def iter_zip_lines(path: str) -> Iterator[Tuple[str, Iterator[str]]]:
    # Yields (member_name, line_iter)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            member = info.filename
            _, ext = os.path.splitext(member.lower())
            if ext not in TEXT_EXTENSIONS:
                # Try sniffing first 4KB
                try:
                    with z.open(info, "r") as f:
                        sample = f.read(4096)
                    if is_binary_sniff(sample):
                        continue
                except Exception:
                    continue
            def line_iter() -> Iterator[str]:
                with z.open(info, "r") as f:
                    for raw in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                        yield raw
            yield member, line_iter()


def compile_patterns(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def search_stream(file_id: str, lines: Iterator[str], regexes: List[re.Pattern], context: int) -> Iterator[Tuple[Match, List[str], List[str]]]:
    prev: deque[str] = deque(maxlen=context)
    for i, line in enumerate(lines, start=1):
        matched: Optional[str] = None
        for rgx in regexes:
            if rgx.search(line):
                matched = rgx.pattern
                break
        if matched is None:
            prev.append(line)
            continue
        # Collect next context lines
        next_lines: List[str] = []
        # We need to peek ahead, which is not trivial on iterators.
        # Simpler: print only previous context; next context omitted for streaming simplicity.
        m = Match(file_id, i, line, matched)
        yield m, list(prev), next_lines
        prev.clear()
    # Done


def walk_files(root: str) -> Iterator[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden dirs by default
        dirnames[:] = [d for d in dirnames if not d.startswith('.')]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def scan(root: str, patterns: List[str], include_all_text_like: bool, max_bytes: int, context: int) -> int:
    compiled = compile_patterns(patterns)
    matches = 0
    for path in walk_files(root):
        try:
            size = os.path.getsize(path)
        except Exception:
            continue
        if size > max_bytes:
            continue
        if not should_scan_file(path, include_all_text_like):
            continue
        lower = path.lower()
        _, ext = os.path.splitext(lower)
        try:
            if ext == ".gz":
                for m, prev_ctx, next_ctx in search_stream(path, iter_gz_lines(path), compiled, context):
                    print(f"\n==> {m.file_path}:{m.line_no} (pattern: {m.pattern})")
                    for c in prev_ctx:
                        sys.stdout.write(f"    - {c}")
                    print(f"    > {m.line}")
                    for c in next_ctx:
                        sys.stdout.write(f"    + {c}")
                    matches += 1
            elif ext == ".zip":
                for member, line_iter in iter_zip_lines(path):
                    file_id = f"{path}!{member}"
                    for m, prev_ctx, next_ctx in search_stream(file_id, line_iter, compiled, context):
                        print(f"\n==> {m.file_path}:{m.line_no} (pattern: {m.pattern})")
                        for c in prev_ctx:
                            sys.stdout.write(f"    - {c}")
                        print(f"    > {m.line}")
                        for c in next_ctx:
                            sys.stdout.write(f"    + {c}")
                        matches += 1
            else:
                for m, prev_ctx, next_ctx in search_stream(path, iter_text_lines(path), compiled, context):
                    print(f"\n==> {m.file_path}:{m.line_no} (pattern: {m.pattern})")
                    for c in prev_ctx:
                        sys.stdout.write(f"    - {c}")
                    print(f"    > {m.line}")
                    for c in next_ctx:
                        sys.stdout.write(f"    + {c}")
                    matches += 1
        except Exception as e:
            print(f"[WARN] Failed reading {path}: {e}", file=sys.stderr)
    return matches


def main():
    ap = argparse.ArgumentParser(description="Scan recursively for cashout/dump-related log lines")
    ap.add_argument("--root", default=os.getcwd(), help="Root directory to scan")
    ap.add_argument("--context", type=int, default=2, help="Lines of context before matches")
    ap.add_argument("--include-all-text-like", action="store_true", help="Try scanning any text-like file, not just known extensions")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES, help="Skip files larger than this many bytes")
    ap.add_argument("--pattern", action="append", default=[], help="Additional regex pattern to include (case-insensitive)")
    args = ap.parse_args()

    patterns = DEFAULT_PATTERNS[:] + args.pattern

    print(f"Scanning {args.root} ...")
    print(f"Patterns: {patterns}")
    total = scan(args.root, patterns, args.include_all_text_like, args.max_bytes, args.context)
    if total == 0:
        print("No matches found.")
    else:
        print(f"\nTotal matches: {total}")

if __name__ == "__main__":
    main()
