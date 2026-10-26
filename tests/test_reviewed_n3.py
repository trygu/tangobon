"""N3 approvals remain exact, bound occurrences and preserve earlier batches."""
import hashlib
import json
import sqlite3
from pathlib import Path

from tangobon.builder import build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


def test_n3_full_batch_preserves_prior_content(tmp_path):
    spec = json.loads((DATA / "reviewed_n3_content.json").read_text())
    raw = (DATA / "reviews/trygve-n3-submission-2026-10-26.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == spec["submission_sha256"]
    assert len(spec["sentences"]) == 161
    assert {s["review_id"] for s in spec["sentences"]} == {f"CR{n:03}" for n in range(50, 211)}
    target = tmp_path / "n3.sqlite"
    batches = [DATA / name for name in ("reviewed_content.json", "reviewed_n4_content.json", "reviewed_n3_content.json")]
    stats = build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target,
                         jlpt_dir=DATA, supplement_path=DATA / "reading_supplement.tsv",
                         reviewed_content_path=batches)
    assert stats["reviewed_sentences"] == 208
    assert stats["reviewed_occurrence_repairs"] == 2
    with sqlite3.connect(target) as conn:
        for path in batches:
            for item in json.loads(path.read_text())["sentences"]:
                assert conn.execute("SELECT text,translation FROM word_sentences WHERE sent_id=? AND surface=?",
                                    (item["sent_id"], item["surface"])).fetchone() == (item["text"], item["translation"])
        for item in spec["sentences"]:
            assert len(item["text"]) <= 26
            assert item["text"].count(item["target_form"]) == 1
            assert conn.execute("SELECT lemma,reading,entry_ref FROM sentence_tokens WHERE sent_id=? AND form=?",
                                (item["sent_id"], item["target_form"])).fetchall() == [
                (item["surface"], item["target_reading"], item["ent_seq"])]
        # Alternate approved occurrences never replace the dictionary's default.
        assert conn.execute("SELECT reading FROM word WHERE surface='良い' AND ent_seq='1605820'").fetchone() == ("よい",)
        assert conn.execute("SELECT reading FROM word WHERE surface='銅' AND ent_seq='1582390'").fetchone() == ("あかがね",)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1005
