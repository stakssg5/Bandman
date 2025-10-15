#!/usr/bin/env python3
"""
CLI utility to extract payment card info signals from free-form text.
- Validates PAN candidates using Luhn; masks by default
- Normalizes and checks expiry (MM/YY, not expired)
- Detects presence of CVV/CVC tokens (does not capture values)
- Heuristic postal/address presence

Usage examples:
  python3 extract_card_info.py --text "(Jane Doe) 4111 1111 1111 1111 12/29 CVV 123 ZIP 94105"
  python3 extract_card_info.py --file ./sample.txt --pretty
  echo "..." | python3 extract_card_info.py
"""

from __future__ import annotations

import argparse
import calendar
import json
import time
import re
import sys
from datetime import date
from typing import Any, Dict, Optional, List

# Patterns
CARD_CANDIDATE_PATTERN = re.compile(r"((?:\d[ -]?){12,18}\d)")  # 13–19 digits with spaces/dashes
EXPIRY_PATTERN = re.compile(r"\b(0[1-9]|1[0-2])[\/-](\d{2}|\d{4})\b")
CVV_TOKEN_PATTERN = re.compile(r"\b(?:CVV|CVC|CID)\b", re.IGNORECASE)

POSTAL_PATTERNS = [
    re.compile(r"\b\d{5}(?:-\d{4})?\b"),  # US ZIP
    re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b", re.IGNORECASE),  # Canada
    re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE),  # UK
    re.compile(r"\b\d{1,5}\s+[A-Za-z][A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct)\b", re.IGNORECASE),  # simple street
]


def _luhn_check(pan: str) -> bool:
    total = 0
    reverse_digits = list(map(int, pan[::-1]))
    for idx, digit in enumerate(reverse_digits):
        if idx % 2 == 1:
            doubled = digit * 2
            if doubled > 9:
                doubled -= 9
            total += doubled
        else:
            total += digit
    return total % 10 == 0


def _normalize_and_validate_expiry(mm: str, yy: str) -> Optional[str]:
    month = int(mm)
    year = int(yy)
    if len(yy) == 2:
        year += 2000
    current_year = date.today().year
    if year < 2000 or year > current_year + 20:
        return None
    last_day = calendar.monthrange(year, month)[1]
    expiry_day = date(year, month, last_day)
    if expiry_day < date.today():
        return None
    return f"{str(month).zfill(2)}/{str(year % 100).zfill(2)}"


def extract_card_info(text: str, return_full_pan: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "cardholder_name": None,
        "card_number": None,             # masked by default (e.g., ************1234)
        "expiry_date": None,             # MM/YY if valid and not expired
        "cvv_cvc_present": False,        # presence only; do not capture/store CVV
        "postal_address_present": False,
    }

    # Cardholder name (naive: first parentheses group)
    name_match = re.search(r"\(([^)]+)\)", text)
    if name_match:
        result["cardholder_name"] = name_match.group(1).strip()

    # Card number: find candidates, normalize, Luhn-validate, select first valid
    for raw in CARD_CANDIDATE_PATTERN.findall(text):
        pan = re.sub(r"[ -]", "", raw)
        if 13 <= len(pan) <= 19 and pan.isdigit() and _luhn_check(pan):
            result["card_number"] = pan if return_full_pan else ("*" * (len(pan) - 4)) + pan[-4:]
            break

    # Expiry date
    expiry_match = EXPIRY_PATTERN.search(text)
    if expiry_match:
        mm, yy = expiry_match.group(1), expiry_match.group(2)
        normalized = _normalize_and_validate_expiry(mm, yy)
        if normalized:
            result["expiry_date"] = normalized

    # CVV/CVC token presence
    if CVV_TOKEN_PATTERN.search(text):
        result["cvv_cvc_present"] = True

    # Postal/address presence (heuristics)
    for pattern in POSTAL_PATTERNS:
        if pattern.search(text):
            result["postal_address_present"] = True
            break

    return result


def _read_input_from_args(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.file is not None:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            sys.exit(2)
    # Fallback to stdin
    data = sys.stdin.read()
    if not data:
        print("Error: no input provided. Use --text, --file, or pipe data via stdin.", file=sys.stderr)
        sys.exit(2)
    return data


def _run_progress(stages: List[str], delay_seconds: float, use_spinner: bool) -> None:
    """Print progress messages to stderr, optionally with a spinner.

    Each stage is displayed for roughly delay_seconds. If use_spinner is True,
    a spinner animates during that period; otherwise we sleep between prints.
    """
    if not stages:
        return
    delay = max(0.05, delay_seconds)
    spinner_frames = ["|", "/", "-", "\\"]
    for stage in stages:
        if use_spinner:
            end_time = time.time() + delay
            frame_index = 0
            while time.time() < end_time:
                sys.stderr.write(f"\r{stage} {spinner_frames[frame_index % len(spinner_frames)]}")
                sys.stderr.flush()
                time.sleep(0.1)
                frame_index += 1
            sys.stderr.write(f"\r{stage} ... done\n")
            sys.stderr.flush()
        else:
            sys.stderr.write(f"{stage}...\n")
            sys.stderr.flush()
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract card info signals from text")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--text", type=str, help="Raw text input")
    input_group.add_argument("--file", type=str, help="Path to a text file to read")
    parser.add_argument("--full-pan", action="store_true", help="Return full PAN (ensure compliance)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--progress", action="store_true", help="Show progress stages to stderr before output")
    parser.add_argument("--stages", type=str, help="Custom progress stages separated by '|' or ','")
    parser.add_argument("--progress-delay", type=float, default=0.6, help="Seconds per stage (spinner duration or sleep)")
    parser.add_argument("--spinner", action="store_true", help="Animate a spinner for each stage")

    args = parser.parse_args()

    text = _read_input_from_args(args)

    if args.progress:
        # Default neutral stages; can be overridden via --stages
        if args.stages:
            raw = args.stages
            stages = [s.strip() for s in re.split(r"[|,]", raw) if s.strip()]
        else:
            stages = [
                "Scanning input",
                "Validating patterns",
                "Normalizing fields",
                "Finalizing",
            ]
        _run_progress(stages, args.progress_delay, args.spinner)

    result = extract_card_info(text, return_full_pan=args.full_pan)

    if args.pretty:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
