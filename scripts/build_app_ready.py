#!/usr/bin/env python3
"""
build_app_ready.py   (v2 - works for Arabic, French AND English speakers)
=========================================================================
STEP 1 of the app: build a small, safe dataset for exercises.

Reads   data/processed/master_cleaned.csv  (+ master_quality.csv for the flags)
Writes  data/processed/app_ready.csv                    lesson rows
        data/processed/reports/app_ready_summary.csv    what each rule removed
        data/processed/reports/app_ready_coverage.csv   rows per language x prompt language

IDEA: the learner chooses their base language (ar / fr / en). A row is kept if it has
at least ONE usable prompt. Every row gets has_ar / has_fr / has_en columns, so the app
can later ask: "give me Wolof sentences that have a French prompt".
Bad translations (web links, wrong script) are set to empty - the row survives if another
prompt is fine.

Usage:
    python scripts/build_app_ready.py
    python scripts/build_app_ready.py --max-words 12 --lang wol fuc
    python scripts/build_app_ready.py --prompts fr en        # only keep fr/en prompts
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

# Flags that make the NATIVE text unusable -> drop the whole row.
# (arabic_column_* flags are not here: they only affect the Arabic prompt, which we validate ourselves.)
BAD_FLAGS = {"repetition_loop", "footnote_marks", "native_equals_arabic",
             "native_script_mismatch", "long_text"}
PROMPT_COLS = {"ar": "text_arabic", "fr": "text_french", "en": "text_english"}
ARABIC_RE = re.compile(r"[؀-ۿ]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")
URL_RE = re.compile(r"https?://|www\.", re.I)
MIN_PLAYABLE = 300          # rows per (language, prompt language) before we call it a gap


def find_root(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).resolve()
        if (p / "data" / "processed").is_dir():
            return p
        sys.exit(f"[error] {p} has no data/processed/")
    for start in [Path.cwd().resolve(), Path(globals().get("__file__", ".")).resolve().parent]:
        for cand in [start, *start.parents]:
            if (cand / "data" / "processed").is_dir():
                return cand
    sys.exit("[error] project root not found. Use --root /path/to/mauritanian-langs")


def read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False, na_values=[""])


def col(df: pd.DataFrame, names: list[str]) -> str | None:
    low = {c.lower(): c for c in df.columns}
    return next((low[n] for n in names if n in low), None)


def attach_flags(clean: pd.DataFrame, qual: pd.DataFrame | None) -> pd.Series:
    """Return one 'flags' string per clean row (empty string if unknown)."""
    if qual is None:
        return pd.Series("", index=clean.index)
    fcol = col(qual, ["quality_flags", "flags", "quality_flag", "flag", "issues"])
    if fcol is None:
        print("[warn] no flags column in master_quality.csv - flags not applied")
        return pd.Series("", index=clean.index)
    key_c = col(clean, ["master_id", "id", "row_id", "record_id", "uid"])
    key_q = col(qual, ["master_id", "id", "row_id", "record_id", "uid"])
    if key_c and key_q:                                   # safest: join on an id
        m = clean[[key_c]].merge(qual[[key_q, fcol]], left_on=key_c, right_on=key_q, how="left")
        return m[fcol].fillna("").set_axis(clean.index)
    if len(clean) == len(qual):                           # fallback: same row order
        print("[info] no shared id column - aligning flags by row position")
        return qual[fcol].fillna("").set_axis(clean.index)
    sys.exit("[error] cannot match master_quality.csv to master_cleaned.csv "
             "(different lengths and no shared id column). Send me both header lines.")


def has_bad_flag(s: str) -> bool:
    parts = {p.strip().strip("[]'\" ") for p in re.split(r"[;,|]", s or "")}
    return bool(parts & BAD_FLAGS)


def valid_prompt(s, code: str, max_words: int) -> bool:
    """Is this translation usable as an exercise prompt?"""
    if not isinstance(s, str) or not s.strip() or URL_RE.search(s):
        return False
    if len(s.split()) > max_words + 10:        # prompts may be a bit longer than the answer
        return False
    if code == "ar":
        return bool(ARABIC_RE.search(s))
    return bool(LATIN_RE.search(s)) and not ARABIC_RE.search(s)   # French / English must be Latin script


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root")
    ap.add_argument("--max-words", type=int, default=15, help="max words in native text (default 15)")
    ap.add_argument("--levels", nargs="+", default=["word", "phrase", "sentence"])
    ap.add_argument("--lang", nargs="+", default=None, help="keep only these language codes, e.g. wol fuc")
    ap.add_argument("--sep", default=",", help='column separator of the output CSV (use ";" if Excel puts everything in one column)')
    ap.add_argument("--prompts", nargs="+", default=["ar", "fr", "en"], choices=["ar", "fr", "en"],
                    help="prompt languages to support (default: ar fr en)")
    args = ap.parse_args()

    root = find_root(args.root)
    proc = root / "data" / "processed"
    clean = read(proc / "master_cleaned.csv")
    qpath = proc / "master_quality.csv"
    qual = read(qpath) if qpath.exists() else None

    df = clean.copy()
    df["_flags"] = attach_flags(clean, qual)
    steps: list[tuple[str, int]] = [("start (master_cleaned.csv)", len(df))]

    def keep(mask: pd.Series, label: str) -> None:
        nonlocal df
        df = df[mask.loc[df.index]]
        steps.append((label, len(df)))

    if args.lang:
        keep(df["language_code"].isin(args.lang), f"language in {args.lang}")
    keep(df["level"].isin(args.levels), f"level in {args.levels}")
    keep(df["text_native"].notna(), "has native text")
    keep(~df["text_native"].fillna("").str.contains(URL_RE), "native text has no web link")
    keep(df["text_native"].fillna("").str.split().str.len() <= args.max_words,
         f"native text <= {args.max_words} words")
    keep(~df["_flags"].map(has_bad_flag), "no bad quality flags")

    # Validate each prompt language separately; blank out the bad ones
    for code in args.prompts:
        c = PROMPT_COLS[code]
        ok = df[c].map(lambda s, k=code: valid_prompt(s, k, args.max_words))
        df.loc[~ok, c] = pd.NA
        df[f"has_{code}"] = ok
    for code in PROMPT_COLS:                    # prompt languages not requested are disabled
        if code not in args.prompts:
            df[PROMPT_COLS[code]] = pd.NA
            df[f"has_{code}"] = False
    keep(df[[f"has_{c}" for c in args.prompts]].any(axis=1), f"has at least one usable prompt {args.prompts}")

    df = df.drop_duplicates(subset=["language_code", "text_native"])
    steps.append(("remove duplicates (language + native text)", len(df)))

    out = df.drop(columns=["_flags"]).reset_index(drop=True)
    out["n_prompts"] = out[[f"has_{c}" for c in PROMPT_COLS]].sum(axis=1)
    out.insert(0, "app_id", range(1, len(out) + 1))
    out.to_csv(proc / "app_ready.csv", index=False, encoding="utf-8-sig", sep=args.sep)   # utf-8-sig: Excel shows Arabic/accents correctly

    (proc / "reports").mkdir(exist_ok=True)
    summ = pd.DataFrame(steps, columns=["rule", "rows_left"])
    summ["removed"] = (-summ["rows_left"].diff()).fillna(0).astype(int)
    summ.to_csv(proc / "reports" / "app_ready_summary.csv", index=False)

    cov = out.groupby("language_code")[[f"has_{c}" for c in PROMPT_COLS]].sum().astype(int)
    cov.columns = [f"prompt_{c}" for c in PROMPT_COLS]
    cov.insert(0, "total_rows", out.groupby("language_code").size())
    cov.to_csv(proc / "reports" / "app_ready_coverage.csv")

    print("\n=== What each rule removed ===")
    print(summ.to_string(index=False))
    print("\n=== Rows per language and level ===")
    print(pd.crosstab(out["language_code"], out["level"], margins=True).to_string())
    print("\n=== Playable rows per language x prompt language (learner's base language) ===")
    print(cov.to_string())
    gaps = [(l, c) for l in cov.index for c in args.prompts if cov.loc[l, f"prompt_{c}"] < MIN_PLAYABLE]
    if gaps:
        print(f"\n[!] GAPS (< {MIN_PLAYABLE} rows): " + ", ".join(f"{l} with {c} prompts" for l, c in gaps))
        print("    -> these learner/language pairs need more translations (see next steps).")
    print(f"\n[done] {len(out):,} rows written to {proc / 'app_ready.csv'}")


if __name__ == "__main__":
    main()
