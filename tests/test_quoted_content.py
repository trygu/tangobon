"""Source quotations must be ordinary, exactly bound sentence occurrences."""
import json
import sqlite3
from pathlib import Path

from tangobon.reviewed_content import apply_reviewed_content
from tangobon.builder import build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


def test_quotes_join_normal_contracts_and_keep_provenance(tmp_path):
    # Build from snapshots, not a developer's existing output database.
    target = tmp_path / "quotes.sqlite"
    build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target)
    conn = sqlite3.connect(target)
    spec = json.loads((DATA / "quoted_content.json").read_text())
    stats = {}
    apply_reviewed_content(conn, DATA / "quoted_content.json", stats)
    assert stats["reviewed_sentences"] == 12
    for item in spec["sentences"]:
        assert conn.execute("SELECT text,translation FROM word_sentences WHERE sent_id=? AND surface=?",
                            (item["sent_id"], item["surface"])).fetchone() == (item["text"], item["translation"])
        assert conn.execute("SELECT entry_ref,form,reading,provenance_sha256 FROM verified_occurrences WHERE sent_id=?",
                            (item["sent_id"],)).fetchone() == (item["ent_seq"], item["target_form"], item["target_reading"], spec["review_sha256"])
    sid = "quotation:drifters-80s:kato-gobyomae"
    assert conn.execute("SELECT lemma,form,reading FROM sentence_tokens WHERE sent_id=? ORDER BY pos", (sid,)).fetchall() == [
        ("秒", "秒", "びょう"), ("前", "前", "まえ")]
    assert conn.execute("SELECT reading FROM word WHERE ent_seq='1392580' AND surface='前'").fetchone() == ("まえ",)
    conn.close()
