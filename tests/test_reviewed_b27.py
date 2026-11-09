"""B27: the 女性 entry carries verified occurrence evidence; the 女 N5 card is unchanged."""
import hashlib
import json
import sqlite3
from pathlib import Path

from tangobon.builder import build_sqlite, KANJI_RE

DATA = Path(__file__).resolve().parents[1] / "data"


def test_b27_josei_entry_and_n5_card_preserved(tmp_path):
    spec = json.loads((DATA / "reviewed_b27_content.json").read_text())
    raw = (DATA / "reviews/trygve-b27-2026-11-09.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == spec["review_sha256"]
    assert [s["review_id"] for s in spec["sentences"]] == ["CR375"]
    item = spec["sentences"][0]
    assert (item["surface"], item["reading"], item["ent_seq"]) == ("女性", "じょせい", "1345250")
    assert len(item["text"]) <= 23
    batches = [DATA / name for name in (
        "reviewed_content.json", "reviewed_n4_content.json", "reviewed_n3_content.json",
        "reviewed_n2_content.json", "reviewed_n1_content.json", "reviewed_b27_content.json",
        "quoted_content.json", "reviewed_sentence_quality.json")]
    target = tmp_path / "b27.sqlite"
    stats = build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target,
                         jlpt_dir=DATA, supplement_path=DATA / "reading_supplement.tsv",
                         reviewed_content_path=batches)
    # 23 (CR001-CR025) + 24 (N4) + 161 (N3) + 141 (N2) + 103 (N1) + 1 (B27)
    # + 12 (quoted) + 63 (sentence-quality)
    assert stats["reviewed_sentences"] == 528
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1007
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        sid = item["sent_id"]
        assert conn.execute(
            "SELECT text,translation FROM word_sentences WHERE sent_id=? AND surface=?",
            (sid, item["surface"])).fetchone() == (item["text"], item["translation"])
        assert conn.execute(
            "SELECT lemma,form,reading,entry_ref FROM sentence_tokens WHERE sent_id=? AND form=?",
            (sid, item["target_form"])).fetchall() == [("女性", "女性", "じょせい", "1345250")]
        assert conn.execute(
            "SELECT lemma_reading FROM verified_occurrences WHERE sent_id=? AND entry_ref=? AND form=? AND reading=?",
            (sid, "1345250", "女性", "じょせい")).fetchone() == ("じょせい",)
        # Every kanji token is dictionary-bound and resolved (N1 ruby standard).
        for form, reading, status, bindings in conn.execute(
                "SELECT form,reading,status,bindings_json FROM sentence_token_readings WHERE sent_id=? ORDER BY pos",
                (sid,)):
            if KANJI_RE.search(form):
                assert status == "resolved", (form, status)
                assert reading
                for ref, spelling, lemma_reading, spoken in json.loads(bindings):
                    assert spoken == reading
                    assert conn.execute(
                        "SELECT 1 FROM context_dictionary_readings WHERE entry_ref=? AND spelling=? AND reading=?",
                        (ref, spelling, lemma_reading)).fetchone()
        # B27 is an addition, not a swap: the CR012 女/おonna N5 card is untouched.
        cr012 = "reviewed:trygve:20261025:CR012"
        assert conn.execute("SELECT text FROM sentence WHERE sent_id=?", (cr012,)).fetchone() == (
            "あの女の人は先生です。",)
        assert conn.execute(
            "SELECT entry_ref,form,reading FROM verified_occurrences WHERE sent_id=?",
            (cr012,)).fetchall() == [("1344930", "女", "おんな")]
