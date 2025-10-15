#!/usr/bin/env node
/**
 * Node.js CLI to extract payment card info signals from free-form text.
 * Mirrors the Python version: Luhn validation, expiry normalization, CVV token presence,
 * address heuristics, and optional progress stages with spinner.
 */

const fs = require('fs');

// Patterns
const CARD_CANDIDATE_PATTERN = /((?:\d[ -]?){12,18}\d)/g; // 13–19 digits with spaces/dashes
const EXPIRY_PATTERN = /\b(0[1-9]|1[0-2])[\/\-](\d{2}|\d{4})\b/;
const CVV_TOKEN_PATTERN = /\b(?:CVV|CVC|CID)\b/i;

const POSTAL_PATTERNS = [
  /\b\d{5}(?:-\d{4})?\b/, // US ZIP
  /\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d\b/i, // Canada
  /\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b/i, // UK
  /\b\d{1,5}\s+[A-Za-z][A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct)\b/i, // simple street
];

function luhnCheck(pan) {
  let total = 0;
  const digits = pan.split('').map(Number).reverse();
  for (let idx = 0; idx < digits.length; idx++) {
    let digit = digits[idx];
    if (idx % 2 === 1) {
      let doubled = digit * 2;
      if (doubled > 9) doubled -= 9;
      total += doubled;
    } else {
      total += digit;
    }
  }
  return total % 10 === 0;
}

function normalizeAndValidateExpiry(mm, yy) {
  const month = parseInt(mm, 10);
  let year = parseInt(yy, 10);
  if (yy.length === 2) year += 2000;
  const now = new Date();
  const currentYear = now.getFullYear();
  if (year < 2000 || year > currentYear + 20) return null;
  // Last day of month: day=0 of next month
  const expiryDay = new Date(year, month, 0);
  if (expiryDay < new Date(now.getFullYear(), now.getMonth(), now.getDate())) return null;
  const mmStr = String(month).padStart(2, '0');
  const yyStr = String(year % 100).padStart(2, '0');
  return `${mmStr}/${yyStr}`;
}

function extractCardInfo(text, returnFullPan = false) {
  const result = {
    cardholder_name: null,
    card_number: null,
    expiry_date: null,
    cvv_cvc_present: false,
    postal_address_present: false,
  };

  // Name in parentheses (naive)
  const nameMatch = text.match(/\(([^)]+)\)/);
  if (nameMatch) result.cardholder_name = nameMatch[1].trim();

  // PAN candidates
  const candidates = text.match(CARD_CANDIDATE_PATTERN) || [];
  for (const raw of candidates) {
    const pan = raw.replace(/[ -]/g, '');
    if (pan.length >= 13 && pan.length <= 19 && /^\d+$/.test(pan) && luhnCheck(pan)) {
      result.card_number = returnFullPan ? pan : '*'.repeat(pan.length - 4) + pan.slice(-4);
      break;
    }
  }

  // Expiry
  const expiryMatch = text.match(EXPIRY_PATTERN);
  if (expiryMatch) {
    const normalized = normalizeAndValidateExpiry(expiryMatch[1], expiryMatch[2]);
    if (normalized) result.expiry_date = normalized;
  }

  // CVV/CVC token presence
  if (CVV_TOKEN_PATTERN.test(text)) result.cvv_cvc_present = true;

  // Postal/address presence
  for (const pattern of POSTAL_PATTERNS) {
    if (pattern.test(text)) {
      result.postal_address_present = true;
      break;
    }
  }

  return result;
}

function parseArgs(argv) {
  const args = {
    text: null,
    file: null,
    fullPan: false,
    pretty: false,
    progress: false,
    stages: null,
    progressDelay: 0.6,
    spinner: false,
  };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--text') args.text = argv[++i] ?? null;
    else if (a === '--file') args.file = argv[++i] ?? null;
    else if (a === '--full-pan') args.fullPan = true;
    else if (a === '--pretty') args.pretty = true;
    else if (a === '--progress') args.progress = true;
    else if (a === '--stages') args.stages = argv[++i] ?? null;
    else if (a === '--progress-delay') args.progressDelay = parseFloat(argv[++i] ?? '0.6');
    else if (a === '--spinner') args.spinner = true;
    else if (a === '--help' || a === '-h') {
      printHelp();
      process.exit(0);
    }
  }
  return args;
}

function printHelp() {
  process.stderr.write(`Usage: extract-card-info [--text TEXT | --file FILE] [--full-pan] [--pretty]\n`);
  process.stderr.write(`       [--progress] [--stages \"A|B|C\"] [--progress-delay SECONDS] [--spinner]\n`);
}

function readInputFromArgs(args) {
  if (args.text != null) return args.text;
  if (args.file != null) {
    try {
      return fs.readFileSync(args.file, 'utf8');
    } catch (e) {
      process.stderr.write(`Error: file not found: ${args.file}\n`);
      process.exit(2);
    }
  }
  const data = fs.readFileSync(0, 'utf8');
  if (!data) {
    process.stderr.write('Error: no input provided. Use --text, --file, or pipe data via stdin.\n');
    process.exit(2);
  }
  return data;
}

async function runProgress(stages, delaySeconds, useSpinner) {
  if (!stages || stages.length === 0) return;
  const delay = Math.max(0.05, delaySeconds);
  const spinnerFrames = ['|', '/', '-', '\\'];
  for (const stage of stages) {
    if (useSpinner) {
      const end = Date.now() + delay * 1000;
      let idx = 0;
      while (Date.now() < end) {
        process.stderr.write(`\r${stage} ${spinnerFrames[idx % spinnerFrames.length]}`);
        await new Promise(r => setTimeout(r, 100));
        idx++;
      }
      process.stderr.write(`\r${stage} ... done\n`);
    } else {
      process.stderr.write(`${stage}...\n`);
      await new Promise(r => setTimeout(r, delay * 1000));
    }
  }
}

async function main() {
  const args = parseArgs(process.argv);
  const text = readInputFromArgs(args);

  if (args.progress) {
    let stages;
    if (args.stages) {
      stages = args.stages.split(/[|,]/).map(s => s.trim()).filter(Boolean);
    } else {
      stages = ['Scanning input', 'Validating patterns', 'Normalizing fields', 'Finalizing'];
    }
    await runProgress(stages, args.progressDelay, args.spinner);
  }

  const result = extractCardInfo(text, args.fullPan);
  if (args.pretty) {
    process.stdout.write(JSON.stringify(result, null, 2) + '\n');
  } else {
    process.stdout.write(JSON.stringify(result) + '\n');
  }
}

if (require.main === module) {
  main();
}
