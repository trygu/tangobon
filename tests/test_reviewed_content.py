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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1007
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


def test_sentence_supersession_preserves_history_and_retires_all_old_links(baseline):
    spec = json.loads((DATA / 'reviewed_sentence_quality.json').read_text())
    with connection(baseline) as conn:
        originals = {}
        for item in spec['sentences']:
            sid = item['supersedes']['sent_id']
            originals[sid] = (conn.execute('SELECT * FROM sentence WHERE sent_id=?', (sid,)).fetchone(),
                              conn.execute('SELECT * FROM sentence_token WHERE sent_id=? ORDER BY pos', (sid,)).fetchall())
            assert conn.execute('SELECT COUNT(*) FROM word_sentences WHERE sent_id=?', (sid,)).fetchone()[0] > 0
        apply_reviewed_content(conn, DATA / 'reviewed_sentence_quality.json', {})
        for item in spec['sentences']:
            sid = item['supersedes']['sent_id']
            assert conn.execute('SELECT * FROM sentence WHERE sent_id=?', (sid,)).fetchone() == originals[sid][0]
            assert conn.execute('SELECT * FROM sentence_token WHERE sent_id=? ORDER BY pos', (sid,)).fetchall() == originals[sid][1]
            assert conn.execute('SELECT COUNT(*) FROM word_sentences WHERE sent_id=?', (sid,)).fetchone()[0] == 0
            assert conn.execute('SELECT text,translation FROM word_sentences WHERE sent_id=? AND surface=?',
                                (item['sent_id'], item['surface'])).fetchone() == (item['text'], item['translation'])
            assert conn.execute('SELECT form,reading,entry_ref FROM sentence_tokens WHERE sent_id=? AND lemma=?',
                                (item['sent_id'], item['surface'])).fetchone() == (item['surface'], item['reading'], item['ent_seq'])


@pytest.mark.parametrize('defect', ['stale_source', 'unapproved_supersession'])
def test_sentence_supersession_fails_closed_and_rolls_back(baseline, tmp_path, defect):
    import hashlib
    spec = json.loads((DATA / 'reviewed_sentence_quality.json').read_text())
    review = json.loads((DATA / spec['source_review']).read_text())
    if defect == 'stale_source':
        # An approved but stale final item must roll back earlier replacements and retirements.
        spec['sentences'][-1]['supersedes']['translation'] = 'Changed upstream'
        review['items'][-1]['supersedes']['translation'] = 'Changed upstream'
    else:
        spec['sentences'][-1]['supersedes']['sent_id'] = 'unapproved'
    review_path = tmp_path / 'review.json'
    review_path.write_text(json.dumps(review))
    spec['source_review'] = str(review_path)
    spec['review_sha256'] = hashlib.sha256(review_path.read_bytes()).hexdigest()
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(spec))
    with connection(baseline) as conn:
        before = conn.execute('SELECT COUNT(*) FROM word_example').fetchone()
        with pytest.raises(ValueError, match='supersession'):
            apply_reviewed_content(conn, path, {})
        assert conn.execute('SELECT COUNT(*) FROM word_example').fetchone() == before
        assert conn.execute("SELECT COUNT(*) FROM sentence WHERE sent_id LIKE 'reviewed:sentence-quality:%'").fetchone()[0] == 0
