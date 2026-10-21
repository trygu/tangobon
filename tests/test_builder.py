"""Build the database from the in-repo snapshots and check the contract views.

The build is expensive (a full streaming pass over both snapshots), so the
database is built once per test module and shared by all tests.
"""

import sqlite3
from pathlib import Path

import pytest

from tangobon.builder import USER_VERSION, build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("tangobon") / "tangobon.sqlite"
    build_sqlite(DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target)
    return target


@pytest.fixture(scope="module")
def conn(db):
    c = sqlite3.connect(db)
    yield c
    c.close()


def test_schema_and_counts(conn):
    assert conn.execute("PRAGMA user_version").fetchone()[0] == USER_VERSION
    words = conn.execute("SELECT COUNT(*) FROM word").fetchone()[0]
    sentences = conn.execute("SELECT COUNT(*) FROM sentence").fetchone()[0]
    assert words > 200_000
    assert sentences > 100_000


def test_kanji_words_contract(conn):
    n = conn.execute("SELECT COUNT(*) FROM kanji_words WHERE kanji='学'").fetchone()[0]
    assert n > 100
    row = conn.execute(
        "SELECT surface, reading, gloss, ke_pri FROM kanji_words"
        " WHERE kanji='学' AND surface='学校'"
    ).fetchone()
    assert row is not None
    assert row[1] == "がっこう"
    assert row[3] is not None
    assert "ichi1" in row[3].split()
    assert "news1" in row[3].split()
    assert "nf01" in row[3].split()


def test_ke_pri_frequency_ordering(conn):
    # ke_pri must let "most important words per kanji" be queried: a tagged
    # top-frequency surface (ichi1) exists for common kanji, and some
    # surfaces carry no tags at all (NULL, not '').
    tagged = conn.execute(
        "SELECT COUNT(*) FROM kanji_words"
        " WHERE kanji='日' AND ke_pri IS NOT NULL AND ke_pri LIKE '%ichi1%'"
    ).fetchone()[0]
    assert tagged > 10
    untagged = conn.execute(
        "SELECT COUNT(*) FROM word WHERE ke_pri IS NULL"
    ).fetchone()[0]
    assert untagged > 10000


def test_word_sentences_contract(conn):
    n = conn.execute(
        "SELECT COUNT(*) FROM word_sentences WHERE surface='学校'"
    ).fetchone()[0]
    assert n >= 1
    row = conn.execute(
        "SELECT text, translation FROM word_sentences WHERE surface='学校' LIMIT 1"
    ).fetchone()
    assert "学校" in row[0]
    assert row[1]


def test_sentences_are_complete(conn):
    empty = conn.execute(
        "SELECT COUNT(*) FROM sentence WHERE text='' OR translation=''"
    ).fetchone()[0]
    assert empty == 0


def test_sentence_tokens_contract(conn):
    q = (
        "SELECT t.lemma, t.form, t.reading FROM sentence_tokens t"
        " JOIN sentence s ON s.sent_id = t.sent_id WHERE s.text = ?"
    )
    rows = conn.execute(q, ("この学校はたくさんの生徒がいます。",)).fetchall()
    assert any(r[0] == "学校" for r in rows)  # the 学校 token is present
    inf = conn.execute(
        q + " AND t.lemma = '居る'", ("この学校はたくさんの生徒がいます。",)
    ).fetchone()
    assert inf == ("居る", "います", "いる")  # lemma / form / occurrence reading


def test_token_form_distinguishes_homographs(conn):
    # The 遭った sentence is linked to the 会う entry: the B: line gives lemma
    # 会う but form 遭った, and the sentence text never contains 会う. The
    # identity filter must be able to see both facts.
    rows = conn.execute(
        "SELECT t.lemma, t.form FROM sentence_tokens t"
        " JOIN sentence s ON s.sent_id = t.sent_id"
        " WHERE s.text = '駅へ行く途中でにわか雨に遭った。'"
    ).fetchall()
    assert ("会う", "遭った") in rows
    assert "会う" not in "駅へ行く途中でにわか雨に遭った。"


def test_entry_refs_match_ent_seq(conn):
    # Wherever a token's lemma is a word in the word table and carries an
    # entry_ref, the ref must be one of that surface's JMdict ent_seqs.
    bad = conn.execute(
        "SELECT COUNT(*) FROM sentence_token t"
        " WHERE t.entry_ref IS NOT NULL"
        " AND EXISTS (SELECT 1 FROM word w WHERE w.surface = t.lemma)"
        " AND NOT EXISTS (SELECT 1 FROM word w"
        "   WHERE w.surface = t.lemma AND w.ent_seq = t.entry_ref)"
    ).fetchone()[0]
    assert bad == 0


def test_token_coverage(conn):
    assert conn.execute("SELECT COUNT(*) FROM sentence_token").fetchone()[0] > 1_000_000
    assert (
        conn.execute("SELECT COUNT(DISTINCT sent_id) FROM sentence_token").fetchone()[0]
        > 100_000
    )


def test_readings_are_optional(conn):
    # Some surfaces carry a k_read, some do not; both must be queryable.
    with_read = conn.execute(
        "SELECT COUNT(*) FROM word WHERE reading IS NOT NULL"
    ).fetchone()[0]
    without = conn.execute("SELECT COUNT(*) FROM word WHERE reading IS NULL").fetchone()[0]
    assert with_read > 0
    assert without > 0
