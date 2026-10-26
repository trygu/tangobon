"""Lexical evidence is independent of reviewer, batch, and sentence-ID spelling."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tangobon.builder import _SCHEMA
from tangobon.reviewed_content import apply_reviewed_content

DATA = Path(__file__).resolve().parents[1] / "data"


def fixture(tmp_path, defect=None):
    spec = json.loads((DATA / "reviewed_n3_content.json").read_text())
    item = copy.deepcopy(next(s for s in spec["sentences"] if s.get("reading_parts")))
    original_id = item["review_id"]
    review = json.loads((DATA / spec["source_review"]).read_text())
    answer = copy.deepcopy(next(a for a in review["items"] if a["id"] == original_id))
    item["review_id"] = answer["id"] = "opaque-answer-7"
    item["sent_id"] = "opaque-sentence-42"
    response = {"review_metadata": {"reviewer": "Unrelated Editor", "reviewed_at": "2031-04-09"}, "items": [answer]}
    raw = json.dumps(response, ensure_ascii=False).encode()
    (tmp_path / "response.json").write_bytes(raw)
    spec.update(source_review="response.json", review_sha256=hashlib.sha256(raw).hexdigest(),
                patches=[], sentences=[item])
    if defect == "misaligned":
        item["reading_parts"][0]["reading"] = "まちがい"
    elif defect == "entry":
        item["tokens"] = [dict(t, entry_ref="missing") if t["form"] == item["target_form"] else t for t in item["tokens"]]
    path = tmp_path / "overlay.json"
    path.write_text(json.dumps(spec, ensure_ascii=False))
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO word VALUES(1,?,?,?,?,?)", (item["ent_seq"], item["surface"], item["reading"], "fixture sense", None))
    return conn, path, item


def test_different_reviewer_and_opaque_identity_preserve_evidence(tmp_path):
    conn, path, item = fixture(tmp_path)
    apply_reviewed_content(conn, path, {})
    assert conn.execute("SELECT sent_id,entry_ref,lemma,lemma_reading,form,reading FROM verified_occurrences").fetchone() == (
        item["sent_id"], item["ent_seq"], item["surface"], item["reading"], item["target_form"], item["target_reading"])
    parts = conn.execute("SELECT written_part,reading_part FROM occurrence_reading_parts ORDER BY pos").fetchall()
    assert "".join(p[0] for p in parts) == item["target_form"]
    assert "".join(p[1] for p in parts) == item["target_reading"]
    # This word/sentence contract contains no app-specific focus/level approval.
    assert not {"level", "focus_kanji", "reviewer"}.intersection(
        row[1] for row in conn.execute("PRAGMA table_info(verified_occurrence)"))


@pytest.mark.parametrize("defect", ["misaligned", "entry"])
def test_invalid_evidence_rolls_back_all_contract_rows(tmp_path, defect):
    conn, path, _ = fixture(tmp_path, defect)
    with pytest.raises(ValueError):
        apply_reviewed_content(conn, path, {})
    for table in ("sentence", "sentence_token", "verified_occurrence", "occurrence_reading_part"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
