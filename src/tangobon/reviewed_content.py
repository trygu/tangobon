"""Strict editorial overlay; upstream snapshots and contract schemas stay intact."""

import hashlib
import json
import re
from pathlib import Path

from .builder import KANA_RE, KANJI_RE


def apply_reviewed_content(conn, path, stats):
    if path is None:
        return
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    if spec["schema_version"] != 1 or not re.fullmatch(r"[0-9a-f]{64}", spec["review_sha256"]):
        raise ValueError("Invalid reviewed-content provenance/version")
    ids = [x["review_id"] for x in spec["patches"] + spec["sentences"] + spec.get("tokenizations", [])]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate review identity")
    review_bytes = (Path(path).parent / spec["source_review"]).read_bytes()
    if hashlib.sha256(review_bytes).hexdigest() != spec["review_sha256"]:
        raise ValueError("Source review hash mismatch")
    approved = {item["id"]: item for item in json.loads(review_bytes)["items"]}
    if set(ids) != set(approved) or any(item["status"] != "answered" for item in approved.values()):
        raise ValueError("Editorial overlay must account for every answered review")
    for item in spec["patches"] + spec["sentences"]:
        answer = approved[item["review_id"]]
        ja = answer.get("replacement_ja") or answer.get("corrected_ja") or answer["original_ja"]
        en = answer.get("replacement_en") or answer.get("corrected_en") or answer["original_en"]
        if item.get("supersedes") != answer.get("supersedes"):
            raise ValueError(f"Unapproved supersession: {item['review_id']}")
        text = item.get("text", item.get("expected_text"))
        occurrence = item.get("target_form", item.get("surface", item.get("form")))
        pronunciation = item.get("target_reading", item["reading"])
        if (text, item["translation"], pronunciation, occurrence) != (ja, en, answer["occurrence_reading"], answer["target_surface"]):
            raise ValueError(f"Content differs from approved answer: {item['review_id']}")

    for item in spec.get("tokenizations", []):
        if item != approved[item["review_id"]].get("tokenization"):
            raise ValueError(f"Tokenization differs from approved answer: {item['review_id']}")

    def kana(value):
        if not KANA_RE.fullmatch(value):
            raise ValueError(f"Reading must be plain kana: {value}")

    # A failed validation cannot leave a partially applied editorial overlay.
    token_delta = 0
    conn.execute("SAVEPOINT reviewed_content")
    try:
        for item in spec.get("tokenizations", []):
            sid = item["sent_id"]
            fields = ("lemma", "form", "reading", "entry_ref")
            expected = [tuple(t[k] for k in fields) for t in item["expected_tokens"]]
            replacement = [tuple(t[k] for k in fields) for t in item["tokens"]]
            actual = conn.execute("SELECT pos,lemma,form,reading,entry_ref FROM sentence_token WHERE sent_id=? ORDER BY pos", (sid,)).fetchall()
            text = conn.execute("SELECT text,translation FROM sentence WHERE sent_id=?", (sid,)).fetchone()
            if text != (item["expected_text"], item["expected_translation"]) or actual != [(pos, *token) for pos, token in enumerate(expected)]:
                raise ValueError(f"Stale tokenization review: {sid}")
            if not replacement or "".join(t[1] for t in expected) != "".join(t[1] for t in replacement):
                raise ValueError(f"Tokenization changes written content: {sid}")
            cursor = 0
            for token in replacement:
                lemma, form, reading, ref = token
                start = text[0].find(form, cursor) if form else -1
                if start < 0:
                    raise ValueError(f"Unaligned tokenization: {sid}")
                cursor = start + len(form)
                if token not in expected:
                    kana(reading or "")
                    if KANJI_RE.search(form) and (ref is None or not conn.execute(
                        "SELECT 1 FROM word WHERE ent_seq=? AND surface=?", (ref, lemma)
                    ).fetchone()):
                        raise ValueError(f"Unbound replacement token: {sid}")
            conn.execute("DELETE FROM sentence_token WHERE sent_id=?", (sid,))
            conn.executemany("INSERT INTO sentence_token VALUES(?,?,?,?,?,?)",
                             [(sid, pos, *token) for pos, token in enumerate(replacement)])
            token_delta += len(replacement) - len(expected)
        for item in spec["patches"]:
            kana(item["reading"])
            row = conn.execute("SELECT text,translation FROM sentence WHERE sent_id=?", (item["sent_id"],)).fetchone()
            if row != (item["expected_text"], item["expected_translation"]):
                raise ValueError(f"Stale sentence correction: {item['review_id']}")
            rows = conn.execute("SELECT pos,reading FROM sentence_token WHERE sent_id=? AND lemma=? AND form=?",
                                (item["sent_id"], item["lemma"], item["form"])).fetchall()
            if len(rows) != 1 or rows[0][1] != item["expected_reading"] or item["expected_text"].count(item["form"]) != 1:
                raise ValueError(f"Stale/ambiguous occurrence correction: {item['review_id']}")
            conn.execute("UPDATE sentence SET translation=? WHERE sent_id=?", (item["translation"], item["sent_id"]))
            conn.execute("UPDATE sentence_token SET reading=? WHERE sent_id=? AND pos=?",
                         (item["reading"], item["sent_id"], rows[0][0]))
        for item in spec["sentences"]:
            kana(item["reading"])
            sid, text = item["sent_id"], item["text"]
            target_form = item.get("target_form", item["surface"])
            target_reading = item.get("target_reading", item["reading"])
            kana(target_reading)
            if not sid or not text or not item["translation"] or text.count(target_form) != 1:
                raise ValueError(f"Invalid/ambiguous reviewed sentence: {sid}")
            row = conn.execute("SELECT word_id,reading FROM word WHERE ent_seq=? AND surface=?",
                               (item["ent_seq"], item["surface"])).fetchone()
            if row is None or row[1] not in (None, item["reading"]):
                raise ValueError(f"Unbound reviewed target: {sid}")
            covered, cursor, target_count = set(), 0, 0
            for token in item["tokens"]:
                kana(token["reading"])
                form = token["form"]
                start = text.find(form, cursor)
                if not form or start < 0:
                    raise ValueError(f"Missing/out-of-order token: {sid} {form}")
                cursor = start + len(form)
                covered.update(range(start, cursor))
                if token["entry_ref"] is not None and not conn.execute(
                    "SELECT 1 FROM word WHERE ent_seq=? AND surface=?", (token["entry_ref"], token["lemma"])
                ).fetchone():
                    raise ValueError(f"Unknown token entry: {sid} {form}")
                if form == target_form:
                    if (token["lemma"], token["reading"], token["entry_ref"]) != (item["surface"], target_reading, item["ent_seq"]):
                        raise ValueError(f"Conflicting target token: {sid}")
                    target_count += 1
            if target_count != 1 or any(KANJI_RE.fullmatch(ch) and i not in covered for i, ch in enumerate(text)):
                raise ValueError(f"Incomplete kanji/target annotation: {sid}")
            parts = item.get("reading_parts", [])
            if parts:
                for part in parts:
                    kana(part["reading"])
                    if len(part["form"]) != 1 or part["kind"] not in ("Kana", "Reviewed word reading", "On’yomi", "Kun’yomi"):
                        raise ValueError(f"Invalid reading breakdown: {sid}")
                if ("".join(p["form"] for p in parts), "".join(p["reading"] for p in parts)) != (target_form, target_reading):
                    raise ValueError(f"Misaligned reading breakdown: {sid}")
            if previous := item.get("supersedes"):
                old = conn.execute("SELECT tanaka_entry,text,translation FROM sentence WHERE sent_id=?",
                                   (previous["sent_id"],)).fetchone()
                if old is None or old[1:] != (previous["text"], previous["translation"]) or previous["sent_id"] == sid:
                    raise ValueError(f"Stale sentence supersession: {item['review_id']}")
                # Keep corpus rows/tokens for historical snapshots, but retire every
                # word-to-example link so a rejected pair cannot return in new selection.
                conn.execute("DELETE FROM word_example WHERE tanaka_entry=?", (old[0],))
            conn.execute("INSERT INTO sentence VALUES(?,?,?,?)", (sid, sid, text, item["translation"]))
            conn.execute("INSERT INTO word_example VALUES(?,?)", (row[0], sid))
            conn.executemany("INSERT INTO sentence_token VALUES(?,?,?,?,?,?)", [
                (sid, i, t["lemma"], t["form"], t["reading"], t["entry_ref"])
                for i, t in enumerate(item["tokens"])
            ])
            identity = (sid, item["ent_seq"], item["surface"], target_form, target_reading)
            conn.execute("INSERT INTO verified_occurrence VALUES(?,?,?,?,?,?,?)",
                         (sid, item["ent_seq"], item["surface"], item["reading"], target_form,
                          target_reading, spec["review_sha256"]))
            conn.executemany("INSERT INTO occurrence_reading_part VALUES(?,?,?,?,?,?,?,?,?)", [
                (*identity, i, part["form"], part["reading"], part["kind"]) for i, part in enumerate(parts)
            ])
        conn.execute("RELEASE reviewed_content")
    except Exception:
        conn.execute("ROLLBACK TO reviewed_content")
        conn.execute("RELEASE reviewed_content")
        raise
    stats["reviewed_sentences"] = stats.get("reviewed_sentences", 0) + len(spec["sentences"])
    stats["reviewed_occurrence_repairs"] = stats.get("reviewed_occurrence_repairs", 0) + len(spec["patches"])
    stats["sentences_with_tokens"] = stats.get("sentences_with_tokens", 0) + len(spec["sentences"])
    stats["tokens"] = stats.get("tokens", 0) + token_delta + sum(len(item["tokens"]) for item in spec["sentences"])
