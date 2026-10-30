"""Approved N1 occurrences remain bound to their lexical sense and context."""
import hashlib
import json
import sqlite3
from pathlib import Path

from tangobon.builder import build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


def test_n1_batch_preserves_occurrences_and_earlier_batches(tmp_path):
    spec = json.loads((DATA / "reviewed_n1_content.json").read_text())
    raw = (DATA / "reviews/trygve-n1-2026-10-27.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == spec["review_sha256"]
    assert {s["review_id"] for s in spec["sentences"]} == {f"CR{n}" for n in range(272, 375)}
    assert len(spec["sentences"]) == 103
    assert sum(len(s["focus_kanji"]) for s in spec["sentences"]) == 105
    batches = [DATA / name for name in (
        "reviewed_content.json", "reviewed_n4_content.json", "reviewed_n3_content.json",
        "reviewed_n2_content.json", "reviewed_n1_content.json", "quoted_content.json",
        "reviewed_sentence_quality.json")]
    target = tmp_path / "n1.sqlite"
    build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target,
                 jlpt_dir=DATA, supplement_path=DATA / "reading_supplement.tsv",
                 reviewed_content_path=batches)
    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1007
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # The sentence-quality batch retires superseded links; those rows stay in
        # the corpus but lose their word_sentences membership by design (B40).
        retired = set()
        for path in batches:
            for item in json.loads(path.read_text())["sentences"]:
                if item.get("supersedes"):
                    retired.add(item["supersedes"]["sent_id"])
        for path in batches:
            for item in json.loads(path.read_text())["sentences"]:
                if item["sent_id"] in retired:
                    assert conn.execute("SELECT 1 FROM word_sentences WHERE sent_id=?",
                                        (item["sent_id"],)).fetchone() is None
                    continue
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
        from tangobon.builder import KANJI_RE
        for item in spec["sentences"]:
            rows = conn.execute(
                "SELECT form,reading,status,bindings_json FROM sentence_token_readings WHERE sent_id=? ORDER BY pos",
                (item["sent_id"],)).fetchall()
            for form, reading, status, bindings in rows:
                if KANJI_RE.search(form):
                    assert status == "resolved", (item["sent_id"], form, status)
                    assert reading
                    for ref, spelling, lemma_reading, spoken in json.loads(bindings):
                        assert spoken == reading
                        assert conn.execute(
                            "SELECT 1 FROM context_dictionary_readings WHERE entry_ref=? AND spelling=? AND reading=?",
                            (ref, spelling, lemma_reading)).fetchone()
        by_id = {s["review_id"]: s for s in spec["sentences"]}
        assert (by_id["CR274"]["target_form"], by_id["CR274"]["target_reading"]) == ("炒った", "いった"), \
            "Godan 炒る conjugates 炒った/いった, never いて"
        assert by_id["CR278"]["target_reading"] == "はしご", \
            "梯子 'ladder' here is はしご, never ていし"
        assert (by_id["CR281"]["target_form"], by_id["CR281"]["target_reading"]) == ("叱られます", "しかられます"), \
            "Passive of 叱る is しかられます"
        assert (by_id["CR304"]["surface"], by_id["CR304"]["ent_seq"]) == ("安佚", "1608240"), \
            "佚 binds only through the 安佚 compound"
        assert (by_id["CR295"]["surface"], by_id["CR295"]["target_reading"]) == ("お洒落", "おしゃれ")
        assert by_id["CR278"]["reading_parts"] == [
            {"form": "梯子", "reading": "はしご", "kind": "Reviewed word reading"}]
        for review_id in ("CR278", "CR295", "CR317"):
            item = by_id[review_id]
            parts = conn.execute(
                "SELECT written_part,reading_part,kind FROM occurrence_reading_parts WHERE sent_id=? ORDER BY pos",
                (item["sent_id"],)).fetchall()
            assert parts == [(p["form"], p["reading"], p["kind"]) for p in item["reading_parts"]]
        assert (by_id["CR337"]["target_form"], by_id["CR337"]["target_reading"]) == ("涸れかけて", "かれかけて")
        assert (by_id["CR367"]["target_form"], by_id["CR367"]["target_reading"]) == ("轢かれる", "ひかれる")
