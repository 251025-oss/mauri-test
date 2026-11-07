#!/usr/bin/env python3
"""
scripts/build_master_dataset.py
===============================
Audit, standardise, clean, merge and validate the 9 raw CSV files of the
Mauritanian-languages project into ONE canonical staging file:

    data/processed/master_cleaned.csv      (exactly 10 columns, see CANONICAL_COLUMNS)

Run it from the project root (the folder that contains manage.py):

    python scripts/build_master_dataset.py

Extra files written next to the master file (they never change its 10-column contract):

    data/processed/master_quality.csv             one row per master_id: completeness score, flags, provenance
    data/processed/reports/quarantine.csv         rows that could not be kept (with the reason)
    data/processed/reports/merge_conflicts.csv    values that DIFFER between duplicates (nothing is lost silently)
    data/processed/reports/near_duplicates.csv    near-identical texts for a human to review (never merged)

Pipeline
--------
    discover files -> read (encoding fallback) -> 9 parsers -> canonical records
    -> clean_text on every text field -> quarantine unusable rows
    -> harmonise category spelling -> merge duplicates on (language_code, text_native)
    -> quality flags + score -> near-duplicate report -> run_preflight_checks -> save

Design decisions worth knowing
------------------------------
* Missing-data tokens are exactly: "", nan, none, null, n/a (case-insensitive).
  "na" is NOT one of them: "Na" is a real Soninke word (cattle).
* Nothing linguistic is rewritten silently. Typing substitutes such as "cf" / "6" in Pulaar, repetition
  loops in Wolof, script mismatches... are FLAGGED in master_quality.csv, not "fixed".
* Duplicates are merged, not deleted: non-null values are combined; if two duplicates carry different
  non-null values (e.g. two different Arabic sentences for one Soninke word) the first one by source
  priority is kept and the other is written to merge_conflicts.csv.
* Categories that come from a mapping default (Conversational, General, Culture...) are weaker than
  categories that come from the data, so a real category always wins a merge.

Only needs pandas (already in requirements.txt). rapidfuzz is used for fuzzy matching if installed,
otherwise the standard library (difflib) is used.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

try:  # optional speed-up for the fuzzy report
    from rapidfuzz import fuzz as _rf_fuzz  # type: ignore
except Exception:  # pragma: no cover
    _rf_fuzz = None

log = logging.getLogger("build_master_dataset")

# ----------------------------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "processed"

ENCODINGS = ("utf-8-sig", "utf-8", "cp1256", "latin1")  # tried in this order

VALID_LANGUAGES = {"mey", "fuc", "snk", "wol"}
LANGUAGE_ORDER = ["mey", "fuc", "snk", "wol"]
VALID_LEVELS = {"word", "phrase", "sentence", "paragraph"}
LEVEL_ALIASES = {  # values found in raw files -> canonical level
    "word": "word", "phrase": "phrase", "sentence": "sentence", "paragraph": "paragraph",
    "text": "paragraph",  # arabic_soninke.csv uses "text" for its 10 long passages
}

CANONICAL_COLUMNS = [
    "master_id", "language_code", "text_native", "text_arabic", "text_french",
    "text_english", "category", "level", "source_name", "source_url",
]
TEXT_COLUMNS = ["text_native", "text_arabic", "text_french", "text_english", "category", "source_url"]

NULL_TOKENS = {"", "nan", "none", "null", "n/a"}  # compared in lower case, after strip
GENERIC_CATEGORY_VALUES = {"others", "other", "autre", "autres"}  # carry no information -> use default

TIDY_PUNCTUATION = True   # curly quotes / long dashes -> plain ones (never touches letters or diacritics)
REMOVE_TATWEEL = True     # Arabic kashida U+0640 is decoration, not a letter

# Invisible characters that corrupt matching but carry no meaning. ZWNJ (U+200C) and ZWJ (U+200D)
# are deliberately KEPT: they are meaningful in some Arabic-script spellings.
_STRIP_CODEPOINTS = [0x00AD, 0x200B, 0x200E, 0x200F, 0x2060, 0xFEFF] \
    + list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))
_STRIP_TABLE = {cp: None for cp in _STRIP_CODEPOINTS}
if REMOVE_TATWEEL:
    _STRIP_TABLE[0x0640] = None
_PUNCT_TABLE = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"',
    0x2012: "-", 0x2013: "-", 0x2014: "-", 0x2015: "-", 0x2212: "-",
}

ARABIC_SCRIPT = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
LATIN_LETTER = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]")
UUID_LIKE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
FOOTNOTE_MARKS = re.compile(r"\[\d+\]|\^")
PULAAR_SUBSTITUTES = re.compile(r"[a-z]cf[a-z]|\b6[a-z]|[a-z]6[a-z]", re.IGNORECASE)
ENGLISH_NOTE = re.compile(r"^\(?\s*note\b", re.IGNORECASE)


class PipelineError(RuntimeError):
    """Base class for clear, user-facing errors."""


class SchemaError(PipelineError):
    """A raw file does not have the columns we expect."""


class MissingSourceError(PipelineError):
    """One or more of the 9 raw files cannot be found."""


class PreflightError(PipelineError):
    """The final dataframe violates the canonical contract."""


# ----------------------------------------------------------------------------------------------
# 1. Text normalisation
# ----------------------------------------------------------------------------------------------
def clean_text(value, *, tidy_punctuation: bool = TIDY_PUNCTUATION) -> Optional[str]:
    """Return a clean NFC string, or None for missing data.

    Steps: NFC -> drop invisible/control characters -> unify spaces (NBSP, tabs, line breaks, the
    literal two characters backslash-n) -> optional quote/dash tidy -> collapse whitespace -> strip
    -> NFC again -> map missing-data tokens to None.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value)
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_STRIP_TABLE)
    text = "".join(ch for ch in text if ch in "\n\r\t" or unicodedata.category(ch) != "Cc")
    text = text.replace("\\n", " ")  # literal backslash-n found in some raw cells
    if tidy_punctuation:
        text = text.translate(_PUNCT_TABLE)
    text = re.sub(r"\s+", " ", text).strip()  # \s covers NBSP, thin spaces, tabs, newlines
    text = unicodedata.normalize("NFC", text)
    if text.lower() in NULL_TOKENS:
        return None
    return text


def _s(value) -> Optional[str]:
    """A real non-empty string, or None (guards against NaN floats that sneak in through pandas)."""
    return value if isinstance(value, str) and value != "" else None


def word_count(text: Optional[str]) -> int:
    return len(text.split()) if text else 0


# ----------------------------------------------------------------------------------------------
# 2. I/O: discovery and robust reading
# ----------------------------------------------------------------------------------------------
@dataclass
class SourceSpec:
    file_name: str
    prefix: str
    parser: Callable[["SourceFile"], list]
    priority: int


@dataclass
class SourceFile:
    spec: SourceSpec
    path: Path
    df: pd.DataFrame
    encoding: str
    copies_found: int = 1


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_robust(path: Path) -> tuple[pd.DataFrame, str]:
    """Read a CSV as text, trying several encodings. Everything is read as str, empty cells stay ''."""
    last_error: Optional[Exception] = None
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.ParserError as exc:
            raise PipelineError(f"{path.name}: the CSV structure is broken ({exc})") from exc
        df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
        if sum(df[c].str.contains("\ufffd", regex=False).sum() for c in df.columns):
            log.warning("%s: contains U+FFFD replacement characters (encoding %s): text may be damaged", path.name, enc)
        return df, enc
    raise PipelineError(f"{path.name}: cannot be decoded with {ENCODINGS}: {last_error}")


def discover_sources(raw_dir: Path, specs: list, allow_missing: bool = False) -> list[SourceFile]:
    """Find each expected file anywhere under raw_dir (sub-folders included) and read it."""
    if not raw_dir.exists():
        raise PipelineError(f"Raw data folder not found: {raw_dir}")
    index: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(raw_dir.rglob("*.csv")):
        index[p.name.lower()].append(p)

    prefer = ("githup", "github")  # folder name hints: the GitHub download is the reference copy
    found: list[SourceFile] = []
    missing: list[str] = []
    for spec in specs:
        candidates = index.get(spec.file_name.lower(), [])
        if not candidates:
            missing.append(spec.file_name)
            continue
        candidates.sort(key=lambda p: (not any(h in str(p.parent).lower() for h in prefer), str(p)))
        chosen = candidates[0]
        if len(candidates) > 1:
            hashes = {c: _md5(c) for c in candidates}
            if len(set(hashes.values())) == 1:
                log.info("%s: %d identical copies found, using %s", spec.file_name, len(candidates), chosen)
            else:
                log.warning("%s: %d copies with DIFFERENT content found; using %s. Compare: %s",
                            spec.file_name, len(candidates), chosen, {str(k): v[:8] for k, v in hashes.items()})
        df, enc = read_csv_robust(chosen)
        if enc not in ("utf-8-sig", "utf-8"):
            log.warning("%s was read with fallback encoding %s", spec.file_name, enc)
        found.append(SourceFile(spec, chosen, df, enc, len(candidates)))
    if missing:
        msg = f"Missing raw file(s) under {raw_dir}: {', '.join(missing)}"
        if not allow_missing:
            raise MissingSourceError(msg)
        log.warning(msg)
    return found


def _col(df: pd.DataFrame, *aliases: str, required: bool = True, file: str = "") -> Optional[pd.Series]:
    """Case-insensitive column lookup with aliases (e.g. 'sonike' / 'soninke')."""
    lookup = {c.lower(): c for c in df.columns}
    for a in aliases:
        if a.lower() in lookup:
            return df[lookup[a.lower()]]
    if required:
        raise SchemaError(f"{file}: expected a column named one of {aliases}, found {list(df.columns)}")
    return None


# ----------------------------------------------------------------------------------------------
# 3. Parsers: one per raw file -> list of canonical-ish records
# ----------------------------------------------------------------------------------------------
def _records(
    sf: SourceFile, *, prefix: str, lang: str, native: pd.Series, default_category: str,
    level: Callable[[int], str], arabic: Optional[pd.Series] = None, french: Optional[pd.Series] = None,
    english: Optional[pd.Series] = None, category: Optional[pd.Series] = None, url: Optional[pd.Series] = None,
) -> list[dict]:
    """Shared record builder: cleans every field and attaches provenance."""
    out = []
    name = sf.spec.file_name
    n = len(sf.df)

    def get(series: Optional[pd.Series], i: int) -> Optional[str]:
        return clean_text(series.iloc[i]) if series is not None else None

    for i in range(n):
        cat = get(category, i)
        cat_is_default = cat is None or cat.casefold() in GENERIC_CATEGORY_VALUES
        out.append({
            "master_id": f"{prefix}-{i + 1:04d}",
            "language_code": lang,
            "text_native": get(native, i),
            "text_arabic": get(arabic, i),
            "text_french": get(french, i),
            "text_english": get(english, i),
            "category": default_category if cat_is_default else cat,
            "level": level(i),
            "source_name": name,
            "source_url": get(url, i),
            "_cat_default": cat_is_default,
            "_priority": sf.spec.priority,
            "_row": i + 2,  # row number as seen in a spreadsheet (header = row 1)
        })
    return out


def parse_arabic_hassaniya(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="HASS", lang="mey", native=_col(df, "hassaniya", file=f), arabic=_col(df, "arabic", file=f),
        french=_col(df, "french", required=False), english=_col(df, "english", required=False),
        default_category="Conversational", level=lambda i: "phrase")


def parse_arabic_pulaar(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="PUL", lang="fuc", native=_col(df, "pulaar", file=f), arabic=_col(df, "arabic", file=f),
        category=_col(df, "category", required=False), url=_col(df, "source_url", required=False),
        default_category="General", level=lambda i: "sentence")


def parse_arabic_soninke(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    raw_level = _col(df, "level", required=False)
    unknown: Counter = Counter()

    def level(i: int) -> str:
        v = clean_text(raw_level.iloc[i]) if raw_level is not None else None
        if v is None:
            return "sentence"
        mapped = LEVEL_ALIASES.get(v.casefold())
        if mapped is None:
            unknown[v] += 1
            return "sentence"
        return mapped

    recs = _records(
        sf, prefix="SNK", lang="snk", native=_col(df, "soninke", file=f), arabic=_col(df, "arabic", file=f),
        french=_col(df, "french", required=False), category=_col(df, "category", required=False),
        url=_col(df, "source", required=False), default_category="Culture", level=level)
    if unknown:
        log.warning("%s: unknown level values mapped to 'sentence': %s", f, dict(unknown))
    return recs


def parse_arabic_wolof(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="WOL", lang="wol", native=_col(df, "wolof", file=f), arabic=_col(df, "arabic", file=f),
        category=_col(df, "category", required=False), url=_col(df, "source_url", required=False),
        default_category="General", level=lambda i: "sentence")


def parse_trilingual(sf: SourceFile) -> list[dict]:
    """One raw line -> TWO records: Hassaniya (mey) and Pulaar (fuc), sharing the same Arabic."""
    f, df = sf.spec.file_name, sf.df
    arabic = _col(df, "arabic", file=f)
    hass = _col(df, "hassanya", "hassaniya", file=f)
    pul = _col(df, "pulaar", file=f)
    common = dict(arabic=arabic, default_category="Conversational", level=lambda i: "phrase")
    return (_records(sf, prefix="TRIL-HASS", lang="mey", native=hass, **common)
            + _records(sf, prefix="TRIL-PUL", lang="fuc", native=pul, **common))


def parse_hassaniya_stories(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="STORY-HASS", lang="mey", native=_col(df, "sentence", file=f), url=_col(df, "url", required=False),
        category=_col(df, "category", required=False), default_category="Stories", level=lambda i: "sentence")


def parse_pulaar_french_parallel(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="PARA-PUL", lang="fuc", native=_col(df, "original", file=f), french=_col(df, "translated", file=f),
        default_category="Parallel Corpus", level=lambda i: "sentence")


def parse_pulaar_mauritania_sentences(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="SENT-PUL", lang="fuc", native=_col(df, "sentence", file=f),
        default_category="Mauritanian Context", level=lambda i: "paragraph")


def parse_soninke_dictionary(sf: SourceFile) -> list[dict]:
    f, df = sf.spec.file_name, sf.df
    return _records(
        sf, prefix="DICT-SNK", lang="snk", native=_col(df, "sonike", "soninke", file=f),
        french=_col(df, "farancais", "francais", "french", file=f),
        default_category="Lexicon", level=lambda i: "word")


# Source priority = order of this list (1 = strongest). It decides which value is kept in a conflict.
SOURCE_SPECS = [
    SourceSpec("arabic_hassaniya.csv", "HASS", parse_arabic_hassaniya, 1),
    SourceSpec("arabic_pulaar.csv", "PUL", parse_arabic_pulaar, 2),
    SourceSpec("arabic_soninke.csv", "SNK", parse_arabic_soninke, 3),
    SourceSpec("arabic_wolof.csv", "WOL", parse_arabic_wolof, 4),
    SourceSpec("arabic_hassaniya_pulaar_trilingual.csv", "TRIL", parse_trilingual, 5),
    SourceSpec("hassaniya_stories_collection.csv", "STORY-HASS", parse_hassaniya_stories, 6),
    SourceSpec("pulaar_french_parallel_corpus.csv", "PARA-PUL", parse_pulaar_french_parallel, 7),
    SourceSpec("pulaar_mauritania_sentences.csv", "SENT-PUL", parse_pulaar_mauritania_sentences, 8),
    SourceSpec("soninke_french_dictionary.csv", "DICT-SNK", parse_soninke_dictionary, 9),
]


# ----------------------------------------------------------------------------------------------
# 4. Quarantine, category harmonisation, merge
# ----------------------------------------------------------------------------------------------
def quarantine_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split off rows that cannot be a usable native text. Nothing is dropped without a recorded reason."""
    def reason(text: Optional[str]) -> Optional[str]:
        if text is None or (isinstance(text, float) and pd.isna(text)):
            return "empty_native_text"
        if UUID_LIKE.match(text):
            return "technical_identifier"
        if not any(ch.isalpha() for ch in text):
            return "no_letters_in_native_text"  # footnote numbers, bare digits, punctuation only
        return None

    reasons = df["text_native"].map(reason)
    bad = reasons.notna()
    quarantine = df[bad].copy()
    quarantine["reason"] = reasons[bad]
    return df[~bad].copy(), quarantine


def harmonise_categories(df: pd.DataFrame) -> pd.DataFrame:
    """'Vie Quotidienne' / 'Vie quotidienne' -> the most frequent spelling. Case/space variants only."""
    key = df["category"].str.casefold()
    best = (df.assign(_k=key).groupby(["_k", "category"]).size().reset_index(name="n")
              .sort_values(["_k", "n", "category"], ascending=[True, False, True]).drop_duplicates("_k")
              .set_index("_k")["category"])
    changed = int((df["category"] != key.map(best)).sum())
    if changed:
        log.info("Category spelling harmonised on %d rows", changed)
    df = df.copy()
    df["category"] = key.map(best)
    return df


def merge_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Merge rows sharing (language_code, text_native) without discarding metadata.

    Returns (merged dataframe, conflicts dataframe, provenance dict master_id -> list of 'file:row').
    """
    df = df.sort_values(["_priority", "_row"], kind="stable").reset_index(drop=True)
    df = df.astype(object).where(df.notna(), None)
    dup = df.duplicated(["language_code", "text_native"], keep=False)
    singles, dups = df[~dup], df[dup]

    conflicts: list[dict] = []
    provenance: dict = {}
    merged_rows: list[dict] = []

    for (lang, text), g in dups.groupby(["language_code", "text_native"], sort=False):
        g = g.sort_values(["_priority", "_row"], kind="stable")
        primary = g.iloc[0].to_dict()
        out = dict(primary)

        def log_conflict(field_name: str, kept, values: list) -> None:
            distinct = [v for v in dict.fromkeys(values) if v != kept]
            if distinct:
                conflicts.append({
                    "language_code": lang, "text_native": text, "master_id_kept": primary["master_id"],
                    "field": field_name, "value_kept": kept, "values_dropped": " || ".join(map(str, distinct)),
                    "files": "; ".join(dict.fromkeys(g["source_name"])),
                })

        for f in ("text_arabic", "text_french", "text_english", "source_url"):
            vals = [v for v in g[f] if v is not None]
            out[f] = vals[0] if vals else None
            if vals:
                log_conflict(f, out[f], vals)

        real = g[g["_cat_default"] == False]  # noqa: E712 - categories that came from the data
        if len(real):
            out["category"], out["_cat_default"] = real.iloc[0]["category"], False
            log_conflict("category", out["category"], list(real["category"]))
        else:
            out["category"], out["_cat_default"] = primary["category"], True
        out["level"] = primary["level"]
        log_conflict("level", out["level"], list(g["level"]))
        out["source_name"] = "; ".join(dict.fromkeys(g["source_name"]))
        merged_rows.append(out)
        provenance[primary["master_id"]] = [f"{n}:{row}" for n, row in zip(g["source_name"], g["_row"])]

    for mid, n, row in zip(singles["master_id"], singles["source_name"], singles["_row"]):
        provenance[mid] = [f"{n}:{row}"]

    merged = pd.concat([singles, pd.DataFrame(merged_rows, columns=df.columns)], ignore_index=True)
    merged["_lang_order"] = merged["language_code"].map({c: i for i, c in enumerate(LANGUAGE_ORDER)})
    merged = merged.sort_values(["_lang_order", "_priority", "_row"], kind="stable").drop(columns="_lang_order")
    merged = merged.reset_index(drop=True).astype(object)
    merged = merged.where(merged.notna(), None)  # concat/sort can reintroduce NaN: keep ONE missing type
    return merged, pd.DataFrame(conflicts), provenance


# ----------------------------------------------------------------------------------------------
# 5. Quality flags, score, near-duplicates
# ----------------------------------------------------------------------------------------------
def _letter_share(text: str, pattern: re.Pattern) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    return len(pattern.findall(text)) / len(letters) if letters else 0.0


def has_repetition_loop(text: str, repeats: int = 4) -> bool:
    """Same token 4+ times in a row: typical machine-translation failure."""
    tokens = [re.sub(r"\W+", "", t.casefold()) for t in text.split()]
    run = 1
    for a, b in zip(tokens, tokens[1:]):
        run = run + 1 if (a and a == b) else 1
        if run >= repeats:
            return True
    return False


def _fold(text: str) -> str:
    """Aggressive comparison key (NEVER stored): no case, accents, vowel marks, punctuation."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    t = t.casefold().translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"}))
    t = "".join(ch if ch.isalnum() else " " for ch in t)
    return " ".join(t.split())


def quality_flags(row: pd.Series) -> list[str]:
    flags: list[str] = []
    native, arabic, lang = row["text_native"], _s(row["text_arabic"]), row["language_code"]
    if lang == "mey":
        if _letter_share(native, LATIN_LETTER) > 0.5:
            flags.append("native_script_mismatch")  # Hassaniya is written in Arabic script here
    elif _letter_share(native, ARABIC_SCRIPT) > 0.3:
        flags.append("native_script_mismatch")  # Pulaar / Soninke / Wolof are written in Latin script
    if arabic:
        if _letter_share(arabic, LATIN_LETTER) > 0.3:
            flags.append("arabic_column_contains_latin")
        if not ARABIC_SCRIPT.search(arabic):
            flags.append("arabic_column_has_no_arabic")
        if _fold(arabic) == _fold(native):
            flags.append("native_equals_arabic")
    if lang != "mey" and has_repetition_loop(native):
        flags.append("repetition_loop")
    if FOOTNOTE_MARKS.search(native):
        flags.append("footnote_marks")
    if lang == "fuc" and PULAAR_SUBSTITUTES.search(native):
        flags.append("pulaar_typing_substitute")  # 'cf' / '6' typed instead of the hooked letters
    if _s(row["text_english"]) and ENGLISH_NOTE.match(row["text_english"]):
        flags.append("english_column_is_a_note")
    if word_count(native) > 40:
        flags.append("long_text")
    return flags


def completeness_score(row: pd.Series, n_flags: int) -> float:
    """0..1. Translation coverage and provenance count most; every flag costs a little."""
    score = (0.35 * bool(_s(row["text_arabic"])) + 0.20 * bool(_s(row["text_french"]))
             + 0.10 * bool(_s(row["text_english"])) + 0.10 * (not row["_cat_default"])
             + 0.10 * bool(_s(row["source_url"])) + 0.15)
    return round(max(0.0, score - 0.05 * min(n_flags, 3)), 2)


def build_quality_table(df: pd.DataFrame, provenance: dict) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        flags = quality_flags(r)
        rows.append({
            "master_id": r["master_id"],
            "completeness_score": completeness_score(r, len(flags)),
            "flags": ";".join(flags),
            "words_native": word_count(r["text_native"]),
            "words_arabic": word_count(r["text_arabic"]),
            "category_is_default": bool(r["_cat_default"]),
            "n_source_rows": len(provenance.get(r["master_id"], [])),
            "merged_from": "; ".join(provenance.get(r["master_id"], [])),
        })
    return pd.DataFrame(rows)


def near_duplicates(df: pd.DataFrame, threshold: float = 0.92, max_len: int = 250,
                    max_block: int = 600, max_pairs: int = 20000) -> pd.DataFrame:
    """Report (never merge) texts that differ only by punctuation/case/accents, or by a small typo."""
    def ratio(a: str, b: str) -> float:
        if _rf_fuzz is not None:
            return _rf_fuzz.ratio(a, b) / 100.0
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        if sm.real_quick_ratio() < threshold or sm.quick_ratio() < threshold:
            return 0.0
        return sm.ratio()

    pairs: dict = {}
    for lang, g in df.groupby("language_code", sort=False):
        items = [(r.master_id, r.text_native, _fold(r.text_native)) for r in g.itertuples()]
        by_key: dict = defaultdict(list)
        for it in items:
            if it[2]:
                by_key[it[2]].append(it)
        for key, grp in by_key.items():  # same after folding -> similarity 1.0
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    pairs[(grp[i][0], grp[j][0])] = (lang, grp[i], grp[j], 1.0, "same_after_folding")
        cand = [(mid, txt, key) for mid, txt, key in items if 6 <= len(key) <= max_len]
        blocks: dict = defaultdict(list)
        for it in cand:
            blocks[("p", it[2][:4])].append(it)
            blocks[("s", it[2][-4:])].append(it)
        for blk in blocks.values():
            if len(blk) < 2 or len(blk) > max_block:
                continue
            blk = sorted(blk, key=lambda x: len(x[2]))
            for i in range(len(blk)):
                for j in range(i + 1, len(blk)):
                    a, b = blk[i], blk[j]
                    if len(b[2]) - len(a[2]) > 0.1 * len(b[2]):
                        break  # sorted by length: no later item can be close enough
                    if a[2] == b[2] or (a[0], b[0]) in pairs or (b[0], a[0]) in pairs:
                        continue
                    sim = ratio(a[2], b[2])
                    if sim >= threshold:
                        pairs[(a[0], b[0])] = (lang, a, b, round(sim, 3), "fuzzy_match")
            if len(pairs) >= max_pairs:
                log.warning("near-duplicate report capped at %d pairs", max_pairs)
                break
    out = [{"language_code": lang, "master_id_a": a[0], "text_a": a[1], "master_id_b": b[0], "text_b": b[1],
            "similarity": sim, "reason": why} for lang, a, b, sim, why in pairs.values()]
    return pd.DataFrame(out, columns=["language_code", "master_id_a", "text_a", "master_id_b", "text_b",
                                      "similarity", "reason"]).sort_values(["language_code", "similarity"],
                                                                           ascending=[True, False])


# ----------------------------------------------------------------------------------------------
# 6. Pre-flight verification
# ----------------------------------------------------------------------------------------------
def run_preflight_checks(df: pd.DataFrame) -> dict:
    """Raise PreflightError with a readable list of problems; return a small report when all is fine."""
    problems: list[str] = []

    def add(msg: str, ids: Iterable) -> None:
        ids = list(ids)
        if ids:
            problems.append(f"{msg}: {len(ids)} row(s), e.g. {', '.join(map(str, ids[:5]))}")

    if list(df.columns) != CANONICAL_COLUMNS:
        problems.append(f"Columns are {list(df.columns)}, expected exactly {CANONICAL_COLUMNS}")
        raise PreflightError("Pre-flight failed:\n  - " + "\n  - ".join(problems))

    native = df["text_native"]
    add("text_native is missing or empty", df.loc[native.isna() | (native.astype(str).str.strip() == ""), "master_id"])
    add(f"language_code outside {sorted(VALID_LANGUAGES)}", df.loc[~df["language_code"].isin(VALID_LANGUAGES), "master_id"])
    add(f"level outside {sorted(VALID_LEVELS)}", df.loc[~df["level"].isin(VALID_LEVELS), "master_id"])
    add("category is missing", df.loc[df["category"].isna() | (df["category"].astype(str).str.strip() == ""), "master_id"])
    add("source_name is missing", df.loc[df["source_name"].isna(), "master_id"])
    add("master_id is not unique", df.loc[df["master_id"].duplicated(keep=False), "master_id"])

    not_nfc = set()
    for col in TEXT_COLUMNS:
        s = df[col].dropna().astype(str)
        bad = s[s.map(lambda v: unicodedata.normalize("NFC", v) != v)]
        not_nfc.update(df.loc[bad.index, "master_id"])
    add("text is not in Unicode NFC form", sorted(not_nfc))

    dup = df.duplicated(["language_code", "text_native"], keep=False)
    add("duplicate (language_code, text_native) pairs remain", df.loc[dup, "master_id"])

    if problems:
        raise PreflightError("Pre-flight failed:\n  - " + "\n  - ".join(problems))
    return {"rows": len(df), "languages": sorted(df["language_code"].unique())}


# ----------------------------------------------------------------------------------------------
# 7. Orchestration
# ----------------------------------------------------------------------------------------------
def build(raw_dir: Path, out_dir: Path, *, fuzzy_threshold: float = 0.92, skip_fuzzy: bool = False,
          allow_missing: bool = False, bom: bool = False) -> pd.DataFrame:
    sources = discover_sources(raw_dir, SOURCE_SPECS, allow_missing=allow_missing)
    records: list[dict] = []
    per_file: list[tuple] = []
    for sf in sources:
        recs = sf.spec.parser(sf)
        records.extend(recs)
        per_file.append((sf.spec.file_name, len(sf.df), len(recs), sf.encoding))
        log.info("%-42s rows read: %5d -> records: %5d (encoding %s)", sf.spec.file_name, len(sf.df), len(recs), sf.encoding)
    if not records:
        raise PipelineError("No records were produced: nothing to do.")

    ingested = pd.DataFrame(records)
    ingested = ingested.astype(object).where(ingested.notna(), None)  # NaN -> None, one missing-value type
    ok, quarantine = quarantine_rows(ingested)
    ok = harmonise_categories(ok)
    merged, conflicts, provenance = merge_duplicates(ok)
    quality = build_quality_table(merged, provenance)

    master = merged[CANONICAL_COLUMNS].copy()
    run_preflight_checks(master)  # raises PreflightError: nothing is written when the contract is broken

    out_dir.mkdir(parents=True, exist_ok=True)
    reports = out_dir / "reports"
    reports.mkdir(exist_ok=True)
    enc = "utf-8-sig" if bom else "utf-8"
    kw = dict(index=False, encoding=enc, lineterminator="\n")
    master.to_csv(out_dir / "master_cleaned.csv", **kw)
    quality.to_csv(out_dir / "master_quality.csv", **kw)
    q_cols = ["master_id", "language_code", "text_native", "text_arabic", "source_name", "_row", "reason"]
    quarantine[q_cols].rename(columns={"_row": "source_row"}).to_csv(reports / "quarantine.csv", **kw)
    conflicts.to_csv(reports / "merge_conflicts.csv", **kw)
    near = pd.DataFrame()
    if not skip_fuzzy:
        near = near_duplicates(master, threshold=fuzzy_threshold)
        near.to_csv(reports / "near_duplicates.csv", **kw)

    print_summary(per_file, ingested, quarantine, master, conflicts, near, quality, out_dir, skip_fuzzy)
    return master


def print_summary(per_file, ingested, quarantine, master, conflicts, near, quality, out_dir, skip_fuzzy) -> None:
    line = "=" * 74
    print(f"\n{line}\nMASTER DATASET BUILD - SUMMARY\n{line}")
    print(f"Files processed          : {len(per_file)}")
    print(f"Records ingested         : {len(ingested):,}  (the trilingual file counts twice: 1 line = 2 records)")
    print(f"Quarantined (unusable)   : {len(quarantine):,}   -> reports/quarantine.csv")
    if len(quarantine):
        print("   by reason             : " + ", ".join(f"{k}={v}" for k, v in quarantine['reason'].value_counts().items()))
    removed = len(ingested) - len(quarantine) - len(master)
    print(f"Merged duplicates        : {removed:,} record(s) folded into an existing row")
    print(f"Conflicting values logged: {len(conflicts):,}   -> reports/merge_conflicts.csv")
    print(f"ROWS AFTER DEDUPLICATION : {len(master):,}   -> {out_dir / 'master_cleaned.csv'}")
    if not skip_fuzzy:
        print(f"Near-duplicate pairs     : {len(near):,}   -> reports/near_duplicates.csv (review by hand)")
    print("\nRows by language_code:")
    print(master["language_code"].value_counts().reindex(LANGUAGE_ORDER).fillna(0).astype(int).to_string())
    print("\nRows by language_code x level:")
    print(pd.crosstab(master["language_code"], master["level"]).reindex(LANGUAGE_ORDER).fillna(0).astype(int).to_string())
    flagged = int((quality["flags"] != "").sum())
    print(f"\nRows with at least one quality flag: {flagged:,} of {len(quality):,}   -> master_quality.csv")
    print(f"Mean completeness score            : {quality['completeness_score'].mean():.2f}")
    print(f"Pre-flight checks                  : PASSED\n{line}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build data/processed/master_cleaned.csv from the 9 raw CSV files.")
    p.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="folder searched recursively (default: data/raw)")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="output folder (default: data/processed)")
    p.add_argument("--fuzzy-threshold", type=float, default=0.92, help="similarity 0-1 for the near-duplicate report")
    p.add_argument("--skip-fuzzy", action="store_true", help="skip the near-duplicate report (faster)")
    p.add_argument("--allow-missing", action="store_true", help="continue when some raw files are missing")
    p.add_argument("--bom", action="store_true", help="write UTF-8 with BOM (only if you open the CSV in Excel)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles: never crash on Arabic or Pulaar letters
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)-7s %(message)s")
    try:
        build(args.raw_dir, args.out_dir, fuzzy_threshold=args.fuzzy_threshold, skip_fuzzy=args.skip_fuzzy,
              allow_missing=args.allow_missing, bom=args.bom)
    except PreflightError as exc:
        print(f"\nERROR - nothing was written.\n{exc}", file=sys.stderr)
        return 2
    except PipelineError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
