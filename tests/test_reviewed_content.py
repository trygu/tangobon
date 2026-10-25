"""Approved editorial content must survive the real snapshot build and fail closed."""
import copy
import json
import sqlite3
from pathlib import Path

import pytest

from tangobon.builder import build_sqlite
from tangobon.reviewed_content import apply_reviewed_content

DATA = Path(__file__).resolve().parents[1] / "data"
SPEC = json.loads((DATA / "reviewed_content.json").read_text())


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    path = tmp_path_factory.mktemp("reviewed") / "baseline.sqlite"
    build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", path,
                 jlpt_dir=DATA, supplement_path=DATA / "reading_supplement.tsv")
    return path


def connection(baseline):
    conn = sqlite3.connect(":memory:")
    with sqlite3.connect(baseline) as source:
        source.backup(conn)
    return conn


def test_approved_content_contract(baseline):
    with connection(baseline) as conn:
        original = conn.execute("SELECT text,translation FROM sentence WHERE sent_id='68395_231026'").fetchone()
        stats = {}
        apply_reviewed_content(conn, DATA / "reviewed_content.json", stats)
        assert stats["reviewed_sentences"] == 23
        assert stats["reviewed_occurrence_repairs"] == 2
        for item in SPEC["sentences"]:
            assert conn.execute("SELECT text,translation FROM word_sentences WHERE surface=? AND sent_id=?",
                                (item["surface"], item["sent_id"])).fetchone() == (item["text"], item["translation"])
            assert conn.execute("SELECT reading FROM sentence_tokens WHERE sent_id=? AND lemma=? AND entry_ref=?",
                                (item["sent_id"], item["surface"], item["ent_seq"])).fetchone() == (item["reading"],)
        for item in SPEC["patches"]:
            assert conn.execute("SELECT text,translation FROM sentence WHERE sent_id=?", (item["sent_id"],)).fetchone() == (item["expected_text"], item["translation"])
        # Replacements have new identities; original corpus provenance stays intact.
        assert conn.execute("SELECT text,translation FROM sentence WHERE sent_id='68395_231026'").fetchone() == original
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1005
        # An occurrence approval must not replace ambiguous dictionary defaults
        # (e.g. 何 can still bind なに or なん through their own exact evidence).
        assert conn.execute("SELECT reading FROM word WHERE ent_seq='1577100' AND surface='何'").fetchone() == (None,)


@pytest.mark.parametrize("defect", ["unknown_entry", "bad_kana", "stale_patch", "missing_token", "repeated_target", "duplicate_review"])
def test_invalid_review_rolls_back(baseline, tmp_path, defect):
    spec = copy.deepcopy(SPEC)
    spec["source_review"] = str(DATA / SPEC["source_review"])
    if defect == "unknown_entry":
        spec["sentences"][-1]["ent_seq"] = "0"
    elif defect == "bad_kana":
        spec["sentences"][-1]["tokens"][0]["reading"] = "unknown"
    elif defect == "stale_patch":
        spec["patches"][-1]["expected_translation"] = "Changed upstream"
    elif defect == "missing_token":
        spec["sentences"][-1]["tokens"].pop(0)
    elif defect == "repeated_target":
        spec["sentences"][-1]["text"] += spec["sentences"][-1]["surface"]
    else:
        spec["sentences"][-1]["review_id"] = spec["sentences"][0]["review_id"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(spec, ensure_ascii=False))
    with connection(baseline) as conn:
        old = conn.execute("SELECT translation FROM sentence WHERE sent_id='62001_224666'").fetchone()
        with pytest.raises(ValueError):
            apply_reviewed_content(conn, path, {})
        assert conn.execute("SELECT COUNT(*) FROM sentence WHERE sent_id LIKE 'reviewed:%'").fetchone()[0] == 0
        assert conn.execute("SELECT translation FROM sentence WHERE sent_id='62001_224666'").fetchone() == old
