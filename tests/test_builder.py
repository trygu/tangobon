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


def test_readings_are_optional(conn):
    # Some surfaces carry a k_read, some do not; both must be queryable.
    with_read = conn.execute(
        "SELECT COUNT(*) FROM word WHERE reading IS NOT NULL"
    ).fetchone()[0]
    without = conn.execute("SELECT COUNT(*) FROM word WHERE reading IS NULL").fetchone()[0]
    assert with_read > 0
    assert without > 0
