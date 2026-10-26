"""Approved N2 occurrences remain bound to their lexical sense and context."""
import hashlib
import json
import sqlite3
from pathlib import Path

from tangobon.builder import build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


def test_n2_batch_preserves_occurrences_and_earlier_batches(tmp_path):
    spec = json.loads((DATA / "reviewed_n2_content.json").read_text())
    raw = (DATA / "reviews/trygve-n2-submission-2026-10-26.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == spec["submission_sha256"]
    assert {s["review_id"] for s in spec["sentences"]} == {f"CR{n}" for n in range(131, 272)}
    assert len(spec["sentences"]) == 141
    assert sum(len(s["focus_kanji"]) for s in spec["sentences"]) == 146
    batches = [DATA / name for name in (
        "reviewed_content.json", "reviewed_n4_content.json",
        "reviewed_n3_content.json", "reviewed_n2_content.json", "quoted_content.json")]
    target = tmp_path / "n2.sqlite"
    build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target,
                 jlpt_dir=DATA, supplement_path=DATA / "reading_supplement.tsv",
                 reviewed_content_path=batches)
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1006
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        for path in batches:
            for item in json.loads(path.read_text())["sentences"]:
                assert conn.execute(
                    "SELECT text,translation FROM word_sentences WHERE sent_id=? AND surface=?",
                    (item["sent_id"], item["surface"])).fetchone() == (item["text"], item["translation"])
        for item in spec["sentences"]:
            assert len(item["text"]) <= 23
            assert item["text"].count(item["target_form"]) == 1
            assert conn.execute(
                "SELECT lemma,reading,entry_ref FROM sentence_tokens WHERE sent_id=? AND form=?",
                (item["sent_id"], item["target_form"])).fetchall() == [
                    (item["surface"], item["target_reading"], item["ent_seq"])]
            assert conn.execute(
                "SELECT lemma_reading FROM verified_occurrences WHERE sent_id=? AND entry_ref=? AND form=? AND reading=?",
                (item["sent_id"], item["ent_seq"], item["target_form"], item["target_reading"])
            ).fetchone() == (item["reading"],)
        by_id = {s["review_id"]: s for s in spec["sentences"]}
        assert (by_id["CR175"]["surface"], by_id["CR175"]["ent_seq"]) == ("慰める", "1156890"), "Comforting a friend is transitive 慰める, not 慰む"
        assert by_id["CR252"]["ent_seq"] == "1463740", "虹 means rainbow, not the homograph second"
        assert (by_id["CR133"]["target_form"], by_id["CR133"]["target_reading"]) == ("新鮮", "しんせん")
        assert (by_id["CR157"]["target_form"], by_id["CR157"]["target_reading"]) == ("譲った", "ゆずった")
        assert (by_id["CR260"]["target_form"], by_id["CR260"]["target_reading"]) == ("酌んで", "くんで")
