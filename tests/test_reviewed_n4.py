"""N4 uses occurrence evidence without rewriting N5 or dictionary defaults."""
import json
import sqlite3
from pathlib import Path

from tangobon.builder import build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


def test_n4_batch_and_n5_preservation(tmp_path):
    spec = json.loads((DATA / "reviewed_n4_content.json").read_text())
    target = tmp_path / "reviewed.sqlite"
    stats = build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target,
                         jlpt_dir=DATA, supplement_path=DATA / "reading_supplement.tsv",
                         reviewed_content_path=[DATA / "reviewed_content.json", DATA / "reviewed_n4_content.json"])
    assert stats["reviewed_sentences"] == 47
    assert stats["reviewed_occurrence_repairs"] == 2
    assert len(spec["sentences"]) == 24
    assert len({k for x in spec["sentences"] for k in x["focus_kanji"]}) == 25
    with sqlite3.connect(target) as conn:
        for item in spec["sentences"]:
            assert conn.execute("SELECT text,translation FROM word_sentences WHERE sent_id=? AND surface=?",
                                (item["sent_id"], item["surface"])).fetchone() == (item["text"], item["translation"])
            assert conn.execute("SELECT lemma,form,reading,entry_ref FROM sentence_tokens WHERE sent_id=? AND lemma=?",
                                (item["sent_id"], item["surface"])).fetchone() == (item["surface"], item["target_form"], item["target_reading"], item["ent_seq"])
        old = json.loads((DATA / "reviewed_content.json").read_text())
        for item in old["sentences"]:
            assert conn.execute("SELECT text,translation FROM sentence WHERE sent_id=?", (item["sent_id"],)).fetchone() == (item["text"], item["translation"])
        assert conn.execute("SELECT reading FROM word WHERE ent_seq='1311110' AND surface='私'").fetchone() == (None,)
        assert conn.execute("SELECT reading FROM word WHERE ent_seq='2842390' AND surface='私'").fetchone() == (None,)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1006
