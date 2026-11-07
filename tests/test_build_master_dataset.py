"""
Tests for scripts/build_master_dataset.py (no Django and no database needed).

Run from the project root:
    pytest tests/test_build_master_dataset.py -q
"""
import importlib.util
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_master_dataset.py"
spec = importlib.util.spec_from_file_location("build_master_dataset", SCRIPT)
bmd = importlib.util.module_from_spec(spec)
sys.modules["build_master_dataset"] = bmd  # dataclasses need the module to be registered
spec.loader.exec_module(bmd)


# ------------------------------------------------------------------ clean_text
def test_clean_text_nfc_and_spaces():
    decomposed = "n\u0303"  # n + combining tilde
    assert bmd.clean_text(f"  {decomposed}\u00a0a  b ") == "\u00f1 a b"
    assert unicodedata.is_normalized("NFC", bmd.clean_text(decomposed))


def test_clean_text_removes_invisible_characters_but_keeps_letters():
    assert bmd.clean_text("\u200fمرحبا\u200b") == "مرحبا"
    assert bmd.clean_text("\u0253ee \u0257um \u014b \u01b4") == "\u0253ee \u0257um \u014b \u01b4"  # hooked letters survive


def test_clean_text_punctuation_and_literal_newline():
    assert bmd.clean_text("\u2019a\u2013b \u201cx\u201d") == "'a-b \"x\""
    assert bmd.clean_text("line1\\nline2") == "line1 line2"
    assert bmd.clean_text("line1\nline2") == "line1 line2"


@pytest.mark.parametrize("token", ["", "  ", "nan", "NaN", "None", "null", "N/A", None, float("nan")])
def test_clean_text_missing_tokens(token):
    assert bmd.clean_text(token) is None


def test_clean_text_keeps_na_the_soninke_word():
    assert bmd.clean_text("Na") == "Na"


# ------------------------------------------------------------------ quarantine
def _frame(rows):
    base = dict(text_arabic=None, text_french=None, text_english=None, category="General", level="sentence",
                source_name="a.csv", source_url=None, _cat_default=True, _priority=1, _row=2)
    df = pd.DataFrame([{**base, **r} for r in rows])
    return df.astype(object).where(df.notna(), None)


def test_quarantine_reasons():
    df = _frame([
        {"master_id": "A-1", "language_code": "fuc", "text_native": "Jam waali"},
        {"master_id": "A-2", "language_code": "fuc", "text_native": "(1)"},
        {"master_id": "A-3", "language_code": "fuc", "text_native": None},
        {"master_id": "A-4", "language_code": "fuc", "text_native": "123e4567-e89b-12d3-a456-426614174000"},
    ])
    ok, q = bmd.quarantine_rows(df)
    assert list(ok["master_id"]) == ["A-1"]
    assert dict(zip(q["master_id"], q["reason"])) == {
        "A-2": "no_letters_in_native_text", "A-3": "empty_native_text", "A-4": "technical_identifier"}


# ------------------------------------------------------------------ merge
def test_merge_combines_metadata_and_prefers_real_category():
    df = _frame([
        {"master_id": "P-1", "language_code": "fuc", "text_native": "A\u0257a", "text_arabic": "X",
         "category": "General", "_cat_default": True, "_priority": 1, "source_name": "p.csv"},
        {"master_id": "D-1", "language_code": "fuc", "text_native": "A\u0257a", "text_french": "Salut",
         "category": "History", "_cat_default": False, "_priority": 2, "source_name": "d.csv"},
    ])
    merged, conflicts, prov = bmd.merge_duplicates(df)
    assert len(merged) == 1 and conflicts.empty
    row = merged.iloc[0]
    assert row["master_id"] == "P-1"                      # the strongest source keeps its id
    assert row["text_arabic"] == "X" and row["text_french"] == "Salut"
    assert row["category"] == "History" and row["_cat_default"] is False
    assert row["source_name"] == "p.csv; d.csv"
    assert prov["P-1"] == ["p.csv:2", "d.csv:2"]


def test_merge_logs_conflicting_values():
    df = _frame([
        {"master_id": "S-1", "language_code": "snk", "text_native": "Xa", "text_arabic": "one", "_priority": 1},
        {"master_id": "S-2", "language_code": "snk", "text_native": "Xa", "text_arabic": "two", "_priority": 2},
    ])
    merged, conflicts, _ = bmd.merge_duplicates(df)
    assert merged.iloc[0]["text_arabic"] == "one"
    assert list(conflicts["field"]) == ["text_arabic"] and conflicts.iloc[0]["values_dropped"] == "two"


# ------------------------------------------------------------------ preflight
def _master(**over):
    row = dict(master_id="X-1", language_code="fuc", text_native="Jam", text_arabic=None, text_french=None,
               text_english=None, category="General", level="phrase", source_name="a.csv", source_url=None)
    row.update(over)
    return pd.DataFrame([row], columns=bmd.CANONICAL_COLUMNS)


def test_preflight_accepts_valid_frame():
    assert bmd.run_preflight_checks(_master())["rows"] == 1


@pytest.mark.parametrize("bad, fragment", [
    ({"text_native": None}, "text_native is missing"),
    ({"language_code": "xx"}, "language_code outside"),
    ({"level": "text"}, "level outside"),
    ({"text_native": "n\u0303"}, "not in Unicode NFC"),
])
def test_preflight_rejects(bad, fragment):
    with pytest.raises(bmd.PreflightError, match=fragment):
        bmd.run_preflight_checks(_master(**bad))


def test_preflight_rejects_remaining_duplicates():
    df = pd.concat([_master(master_id="X-1"), _master(master_id="X-2")], ignore_index=True)
    with pytest.raises(bmd.PreflightError, match="duplicate"):
        bmd.run_preflight_checks(df)


# ------------------------------------------------------------------ end to end on tiny files
RAW = {
    "arabic_hassaniya.csv": "id,arabic,hassaniya,french,english\n1,مرحبا,هلا,Bonjour,Hello\n2,شكرا,شكرا,Merci,Thanks\n",
    "arabic_pulaar.csv": "id,arabic,pulaar,category,source_url\n1,مرحبا,Jam waali,,http://x\n2,عدد,(1),History,\n",
    "arabic_soninke.csv": "id,level,arabic,soninke,french,category,source\n1,word,بقر,Na,Bovin,Animaux,Livre\n2,text,نص,Gaaxa,Texte,,\n",
    "arabic_wolof.csv": "id,arabic,wolof,category,source_url\n1,مرحبا,Salaam,,\n",
    "arabic_hassaniya_pulaar_trilingual.csv": "arabic,hassanya,pulaar\nمرحبا,هلا,Jam waali\n",
    "hassaniya_stories_collection.csv": "title,url,category,original_language,context,sentence\nT,http://s,others,ar,,جملة\n",
    "pulaar_french_parallel_corpus.csv": "Original,Translated\nA\u0253a,Salut\n",
    "pulaar_mauritania_sentences.csv": "sentence\nHeddii ngam mum\\nbaawo\n",
    "soninke_french_dictionary.csv": "sonike,farancais\nNa,Vache\n",
}


def _write_raw(root: Path) -> Path:
    sub = root / "raw" / "Githup_data"
    sub.mkdir(parents=True)
    for name, content in RAW.items():
        (sub / name).write_text(content, encoding="utf-8-sig")
    return root / "raw"


def test_end_to_end(tmp_path):
    raw = _write_raw(tmp_path)
    out = tmp_path / "processed"
    master = bmd.build(raw, out, skip_fuzzy=True)
    saved = pd.read_csv(out / "master_cleaned.csv", dtype=str, keep_default_na=False, encoding="utf-8")
    assert list(saved.columns) == bmd.CANONICAL_COLUMNS
    assert set(saved["language_code"]) <= bmd.VALID_LANGUAGES
    assert set(saved["level"]) <= bmd.VALID_LEVELS
    assert not saved.duplicated(["language_code", "text_native"]).any()
    # the trilingual line produced one mey and one fuc record that merged with existing rows
    pul = saved[saved["text_native"] == "Jam waali"].iloc[0]
    assert "arabic_hassaniya_pulaar_trilingual.csv" in pul["source_name"] and pul["text_arabic"] == "مرحبا"
    # "(1)" has no letters -> quarantined; "Na" survives; Soninke "text" level became paragraph
    q = pd.read_csv(out / "reports" / "quarantine.csv", dtype=str, keep_default_na=False)
    assert list(q["text_native"]) == ["(1)"]
    na = saved[(saved["language_code"] == "snk") & (saved["text_native"] == "Na")].iloc[0]
    assert na["text_french"] == "Bovin" and na["category"] == "Animaux"  # merged with the dictionary row
    assert saved.loc[saved["text_native"] == "Gaaxa", "level"].iloc[0] == "paragraph"
    assert (out / "master_quality.csv").exists()
    assert len(master) == len(saved)


def test_missing_file_is_a_clear_error(tmp_path):
    raw = _write_raw(tmp_path)
    (raw / "Githup_data" / "arabic_wolof.csv").unlink()
    with pytest.raises(bmd.MissingSourceError, match="arabic_wolof.csv"):
        bmd.build(raw, tmp_path / "processed", skip_fuzzy=True)


def test_wrong_header_is_a_clear_error(tmp_path):
    raw = _write_raw(tmp_path)
    (raw / "Githup_data" / "arabic_wolof.csv").write_text("id,arabic,something\n1,a,b\n", encoding="utf-8-sig")
    with pytest.raises(bmd.SchemaError, match="wolof"):
        bmd.build(raw, tmp_path / "processed", skip_fuzzy=True)


def test_encoding_fallback(tmp_path):
    p = tmp_path / "latin.csv"
    p.write_bytes("a,b\ncaf\xe9,x\n".encode("latin1"))
    df, enc = bmd.read_csv_robust(p)
    assert enc == "cp1256" or enc == "latin1"  # cp1256 decodes any byte; both are acceptable fallbacks
    assert len(df) == 1
