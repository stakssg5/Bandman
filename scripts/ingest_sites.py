#!/usr/bin/env python3
"""
Aggregate login audit logs from multiple website folders into a single
privacy-safe JSONL file for the dashboard.

- Recursively scans provided directories (or accepts files directly)
- Supports JSONL/NDJSON, JSON (array or object with common keys), and CSV
- Normalizes to fields: ts, email_masked, ip, outcome, reason, latency_ms, site
- Applies allowlist filtering for emails/domains (optional)
- Drops any sensitive credential-like fields and NEVER writes plaintext passwords

Usage examples:
  python scripts/ingest_sites.py websites/siteA websites/siteB -o combined_login_audit.jsonl
  python scripts/ingest_sites.py logs/*.jsonl --allowlist allowlist.txt --patterns "*login*.*" "*auth*.*"

Notes:
- If no allowlist is provided, all emails are allowed. Use allowlist to
  restrict to certain users/domains (e.g., "@fin4.com").
- The script attempts to heuristically map column names from various sources.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

SENSITIVE_KEYS = {
    "password", "pass", "pwd", "secret", "token", "access_token", "refresh_token",
    "authorization", "auth", "session", "cookie",
}

# ---------- Helpers: masking and allowlist ----------

def mask_email(email: str) -> str:
    if not isinstance(email, str) or "@" not in email:
        return "invalid"
    local, domain = email.split("@", 1)
    local_masked = (local[:1] + "***") if local else "***"
    return f"{local_masked}@{domain}"


def load_allow_rules(path: Optional[str]) -> List[str]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    rules: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        rules.append(t)
    return rules


def email_allowed(email: str, rules: List[str]) -> bool:
    if not rules:
        return True
    if not isinstance(email, str) or "@" not in email:
        return False
    email_l = email.lower()
    domain_l = email_l.split("@", 1)[1]
    for rule in rules:
        r = rule.strip()
        if not r:
            continue
        rl = r.lower()
        if rl.startswith("re:"):
            pattern = r[3:]
            try:
                if re.fullmatch(pattern, email, flags=re.IGNORECASE):
                    return True
            except re.error:
                # Skip invalid regex rules
                continue
        elif r.startswith("@"):
            if domain_l == rl[1:]:
                return True
        elif any(ch in r for ch in "*?["):
            # Simple fnmatch via regex translation
            regex = "^" + re.escape(r).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            if re.fullmatch(regex, email_l):
                return True
        else:
            if email_l == rl:
                return True
    return False

# ---------- Discovery ----------

DEFAULT_NAME_PATTERNS = [
    "*login*.*", "*auth*.*", "audit*.*", "events*.*",
]
DEFAULT_EXTS = {"jsonl", "ndjson", "csv", "json"}


def discover_files(inputs: List[str], patterns: List[str], exts: set[str]) -> List[Path]:
    candidates: List[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_file():
            if p.suffix.lower().lstrip(".") in exts:
                candidates.append(p)
            continue
        if p.is_dir():
            for pat in patterns:
                for path in p.rglob(pat):
                    if path.suffix.lower().lstrip(".") in exts and path.is_file():
                        candidates.append(path)
    # De-duplicate while preserving order
    seen: set[str] = set()
    unique: List[Path] = []
    for c in candidates:
        s = str(c.resolve())
        if s not in seen:
            seen.add(s)
            unique.append(c)
    return unique

# ---------- Parsing ----------

TS_CANDIDATE_KEYS = [
    "ts", "timestamp", "time", "datetime", "date", "@timestamp",
    "created_at", "event_time",
]
EMAIL_CANDIDATE_KEYS = [
    "email", "user_email", "username", "user", "login", "principal",
]
IP_CANDIDATE_KEYS = [
    "ip", "ip_address", "remote_ip", "client_ip", "source_ip", "src_ip",
]
OUTCOME_CANDIDATE_KEYS = [
    "outcome", "result", "status", "success", "ok", "login_status",
]
REASON_CANDIDATE_KEYS = [
    "reason", "message", "error", "error_reason", "error_message", "detail",
]
LATENCY_CANDIDATE_KEYS = [
    "latency_ms", "duration_ms", "response_time_ms", "time_ms", "duration", "response_time",
]


@dataclass
class NormalizedEvent:
    ts: str
    email_masked: str
    ip: str
    outcome: str
    reason: str
    latency_ms: Optional[int]
    site: str


def parse_timestamp(value) -> Optional[datetime]:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            # Heuristic: seconds vs ms
            if value > 1_000_000_000_000:  # > ~2001 in ms
                return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            if value > 1_000_000_000:  # seconds
                return datetime.fromtimestamp(value, tz=timezone.utc)
            # Very small numbers are probably invalid
            return None
        if isinstance(value, str):
            s = value.strip()
            # ISO 8601 with Z
            if s.endswith("Z"):
                try:
                    # Python 3.11+ supports fromisoformat with Z? Replace to be safe
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except ValueError:
                    pass
            # Plain ISO
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                pass
            # Common formats
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
            ):
                try:
                    return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return None
    except Exception:
        return None


def coerce_outcome(value) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"success", "ok", "true", "passed", "pass"}:
        return "success"
    if s in {"failure", "fail", "false", "error", "denied", "invalid", "bad_password", "blocked"}:
        return "failure"
    # Numeric statuses
    if s.isdigit():
        try:
            code = int(s)
            if 200 <= code < 400:
                return "success"
            if code >= 400:
                return "failure"
        except Exception:
            pass
    return None


def to_int_ms(value) -> Optional[int]:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            # Heuristic: assume "duration" is in seconds if < 1000
            if value < 1_000:
                return int(round(value * 1000))
            return int(value)
        s = str(value).strip().lower()
        if not s:
            return None
        if s.endswith("ms"):
            return int(float(s[:-2]))
        if s.endswith("s"):
            return int(float(s[:-1]) * 1000)
        v = float(s)
        if v < 1_000:
            return int(round(v * 1000))
        return int(v)
    except Exception:
        return None


def pick_first_key(d: Dict[str, object], keys: List[str]) -> Optional[str]:
    for k in keys:
        if k in d:
            return k
        # case-insensitive search
        for dk in d.keys():
            if dk.lower() == k.lower():
                return dk
    return None


def scrub_sensitive_keys(record: Dict[str, object]) -> None:
    for k in list(record.keys()):
        if k.lower() in SENSITIVE_KEYS:
            record.pop(k, None)


def iter_records_from_path(path: Path) -> Iterator[Dict[str, object]]:
    suf = path.suffix.lower()
    if suf in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        scrub_sensitive_keys(obj)
                        yield obj
                except json.JSONDecodeError:
                    continue
        return
    if suf == ".json":
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        # Accept array or object with common array keys
        arr: Optional[List[Dict[str, object]]] = None
        if isinstance(obj, list):
            arr = [x for x in obj if isinstance(x, dict)]
        elif isinstance(obj, dict):
            for key in ("events", "data", "records", "items"):
                v = obj.get(key)
                if isinstance(v, list):
                    arr = [x for x in v if isinstance(x, dict)]
                    break
        if arr:
            for rec in arr:
                scrub_sensitive_keys(rec)
                yield rec
        return
    if suf == ".csv":
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = {k: v for k, v in row.items()}
                scrub_sensitive_keys(rec)
                yield rec
        return


def normalize_record(rec: Dict[str, object], site: str) -> Optional[NormalizedEvent]:
    # Timestamp
    ts_key = pick_first_key(rec, TS_CANDIDATE_KEYS)
    ts_dt = parse_timestamp(rec.get(ts_key)) if ts_key else None
    if not ts_dt:
        return None
    ts_iso = ts_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    # Email -> masked
    email_key = pick_first_key(rec, EMAIL_CANDIDATE_KEYS)
    email_val = str(rec.get(email_key)) if email_key else ""
    email_masked = mask_email(email_val) if email_val else "unknown"

    # IP
    ip_key = pick_first_key(rec, IP_CANDIDATE_KEYS)
    ip_val = str(rec.get(ip_key)) if ip_key else "unknown"

    # Outcome
    outcome_key = pick_first_key(rec, OUTCOME_CANDIDATE_KEYS)
    outcome_val = coerce_outcome(rec.get(outcome_key)) if outcome_key else None
    if not outcome_val:
        # Try deriving from reason/message text
        reason_key_fallback = pick_first_key(rec, REASON_CANDIDATE_KEYS)
        if reason_key_fallback:
            txt = str(rec.get(reason_key_fallback, "")).lower()
            if any(w in txt for w in ("invalid", "fail", "error", "denied", "locked")):
                outcome_val = "failure"
            elif any(w in txt for w in ("success", "ok", "authenticated")):
                outcome_val = "success"
    if not outcome_val:
        return None

    # Reason
    reason_key = pick_first_key(rec, REASON_CANDIDATE_KEYS)
    reason_val = str(rec.get(reason_key)) if reason_key else ""

    # Latency
    latency_key = pick_first_key(rec, LATENCY_CANDIDATE_KEYS)
    latency_val = to_int_ms(rec.get(latency_key)) if latency_key else None

    return NormalizedEvent(
        ts=ts_iso,
        email_masked=email_masked,
        ip=ip_val or "unknown",
        outcome=outcome_val,
        reason=reason_val,
        latency_ms=latency_val,
        site=site,
    )


def deduce_site_from_path(path: Path, strategy: str) -> str:
    if strategy == "file":
        return path.stem
    if strategy == "dir":
        # Use immediate parent directory name
        return path.parent.name or "unknown"
    return "unknown"


def aggregate(inputs: List[str], allowlist_path: Optional[str], output_path: str,
              patterns: List[str], exts: set[str], site_strategy: str,
              dry_run: bool) -> int:
    rules = load_allow_rules(allowlist_path)
    files = discover_files(inputs, patterns, exts)

    out_fp = Path(output_path)
    if not dry_run:
        out_fp.parent.mkdir(parents=True, exist_ok=True)
        # Truncate output
        out_fp.write_text("", encoding="utf-8")

    seen_keys: set[tuple] = set()
    written = 0

    def write_event(ev: NormalizedEvent) -> None:
        nonlocal written
        line = json.dumps({
            "ts": ev.ts,
            "email_masked": ev.email_masked,
            "ip": ev.ip,
            "outcome": ev.outcome,
            "reason": ev.reason,
            "latency_ms": ev.latency_ms,
            "site": ev.site,
        }, ensure_ascii=False)
        with out_fp.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        written += 1

    for path in files:
        site = deduce_site_from_path(path, site_strategy)
        try:
            for rec in iter_records_from_path(path):
                # Optional allowlist filtering by raw email if present
                email_key = pick_first_key(rec, EMAIL_CANDIDATE_KEYS)
                if email_key and not email_allowed(str(rec.get(email_key)), rules):
                    continue
                ev = normalize_record(rec, site)
                if not ev:
                    continue
                key = (ev.ts, ev.email_masked, ev.ip, ev.outcome, ev.site)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                if not dry_run:
                    write_event(ev)
        except Exception:
            # Skip unreadable files silently to be robust
            continue

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate login audit logs from multiple folders (privacy-safe)")
    parser.add_argument("inputs", nargs="+", help="Directories or files to scan")
    parser.add_argument("--output", "-o", default="combined_login_audit.jsonl", help="Path to output JSONL")
    parser.add_argument("--allowlist", default=os.getenv("ALLOWLIST_PATH", "allowlist.txt"), help="Allowlist file path")
    parser.add_argument("--patterns", "-g", nargs="*", default=DEFAULT_NAME_PATTERNS, help="Filename patterns to include (glob)")
    parser.add_argument("--ext", "-e", nargs="*", default=sorted(DEFAULT_EXTS), help="File extensions to include")
    parser.add_argument("--site-from", choices=["dir", "file", "none"], default="dir", help="How to derive site name")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report without writing output")
    args = parser.parse_args()

    written = aggregate(
        inputs=args.inputs,
        allowlist_path=args.allowlist,
        output_path=args.output,
        patterns=list(args.patterns),
        exts=set(e.lower().lstrip(".") for e in args.ext),
        site_strategy=("dir" if args.site_from == "none" else args.site_from),
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"[dry-run] Would write {written} events to {args.output}")
    else:
        print(f"Wrote {written} events to {args.output}")


if __name__ == "__main__":
    main()
