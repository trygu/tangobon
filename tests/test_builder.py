"""Build the database from the in-repo snapshots and check the contract views.

The build is expensive (a full streaming pass over both snapshots), so the
database is built once per test module and shared by all tests.
"""

import re
import sqlite3
from pathlib import Path

import pytest

from tangobon.builder import USER_VERSION, build_sqlite

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("tangobon") / "tangobon.sqlite"
    build_sqlite(
        DATA / "JMdict_e_examp.gz", DATA / "examples.utf.gz", target,
        jlpt_dir=DATA, bonus_dir=DATA / "bonus",
        supplement_path=DATA / "reading_supplement.tsv",
    )
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


def test_reading_supplement(conn):
    # The curated supplement fills approved NULL readings (task 057, Q079).
    row = conn.execute(
        "SELECT reading FROM kanji_words WHERE surface='私たち'"
    ).fetchone()
    assert row == ("わたしたち",)
    # Every supplemented row carries its evidence comment in the TSV; spot
    # check a second filled entry through the contract view.
    row = conn.execute(
        "SELECT reading FROM kanji_words WHERE surface='誰'"
    ).fetchone()
    assert row == ("だれ",)
    # Contested readings are never supplemented: 日本 was resolved only by
    # an explicit user review pick (にほん); multi-entry ambiguities like
    # 父 (ちち/てて/ちゃん across entries) stay unresolved — no silent pick.
    assert conn.execute(
        "SELECT reading FROM kanji_words WHERE surface='日本'"
    ).fetchone() == ("にほん",)
    n_father = conn.execute(
        "SELECT COUNT(DISTINCT reading) FROM word"
        " WHERE surface='父' AND reading IS NOT NULL"
    ).fetchone()[0]
    assert n_father > 1


def test_reading_supplement_strictness(tmp_path):
    # The supplement is an editorial record: unknown pairs, non-kana
    # readings and stale entries (reading already present) fail the build.
    from tangobon.builder import _SCHEMA, _build_reading_supplement

    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT INTO word(ent_seq, surface, reading, gloss)"
        " VALUES('1', '私たち', NULL, 'we')"
    )
    conn.execute(
        "INSERT INTO word(ent_seq, surface, reading, gloss)"
        " VALUES('2', '学校', 'がっこう', 'school')"
    )
    stats = {"supplemented_readings": 0}

    def run(lines):
        path = tmp_path / "sup.tsv"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _build_reading_supplement(conn, path, stats)

    run(["1\t私たち\tわたしたち\tevidence note"])  # fills NULL
    assert conn.execute(
        "SELECT reading FROM word WHERE ent_seq='1'"
    ).fetchone() == ("わたしたち",)
    assert stats["supplemented_readings"] == 1
    with pytest.raises(ValueError, match="no word row"):
        run(["9\t幻\tまぼろし"])
    with pytest.raises(ValueError, match="plain kana"):
        run(["1\t私たち\twatashi7"])
    with pytest.raises(ValueError, match="already has reading"):
        run(["2\t学校\tがくこう"])  # stale: reading already present


def test_jlpt_words_contract(conn):
    # Counts are pinned to the 2026-10-21 OpenJLPT snapshot (commit 0d1d341).
    n = conn.execute("SELECT COUNT(*) FROM jlpt_words").fetchone()[0]
    assert n == 7811
    by_level = dict(conn.execute("SELECT level, COUNT(*) FROM jlpt_words GROUP BY level"))
    assert by_level == {5: 674, 4: 630, 3: 1659, 2: 1778, 1: 3070}
    no_reading = conn.execute(
        "SELECT COUNT(*) FROM jlpt_word WHERE reading IS NULL OR reading = ''"
    ).fetchone()[0]
    assert no_reading == 0


def test_jlpt_levels_are_reading_specific(conn):
    # The level attaches to the (word, reading) pair, not the surface:
    # 明日 is N5 as あした but N4 as あす; 人 is N5 as ひと but N1 as じん.
    asashita = dict(conn.execute(
        "SELECT reading, level FROM jlpt_words WHERE word = '明日'"
    ))
    assert asashita == {"あした": 5, "あす": 4}
    hito = dict(conn.execute(
        "SELECT reading, level FROM jlpt_words WHERE word = '人'"
    ))
    assert hito == {"ひと": 5, "じん": 1}


def test_bonus_phrases_contract(conn):
    # Count pinned to the 2026-10-23 Drifters curation (provenance in
    # data/SNAPSHOTS.txt and the data/bonus/ source field per phrase).
    n = conn.execute(
        "SELECT COUNT(*) FROM bonus_phrases WHERE set_name = 'drifters-80s'"
    ).fetchone()[0]
    assert n == 14
    empty = conn.execute(
        "SELECT COUNT(*) FROM bonus_phrase"
        " WHERE phrase = '' OR reading = '' OR source = '' OR speaker = ''"
    ).fetchone()[0]
    assert empty == 0
    # Kanji-only curation rule: every bonus phrase carries at least one
    # kanji (this project stores kanji words and sentences only).
    kanji_re = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
    kana_only = [
        r[0] for (r,) in conn.execute("SELECT phrase FROM bonus_phrase")
        if not kanji_re.search(r)
    ]
    assert kana_only == []
    # Every row in the set is source-verified.
    assert conn.execute(
        "SELECT COUNT(*) FROM bonus_phrase WHERE verified = 0"
    ).fetchone()[0] == 0
    row = conn.execute(
        "SELECT speaker, reading FROM bonus_phrases WHERE phrase = '次いってみよう'"
    ).fetchone()
    assert row == ("いかりや長介", "つぎ いってみよう")
    # Per-phrase show override (ドリフ大爆笑) is kept; the set default applies
    # elsewhere.
    assert conn.execute(
        "SELECT show FROM bonus_phrases WHERE phrase_id = 'ikaria-tsugi-itte-miyou'"
    ).fetchone()[0] == "ドリフ大爆笑（フジテレビ）"
    assert conn.execute(
        "SELECT show FROM bonus_phrases WHERE phrase_id = 'ikaria-kouhan-shuppatsu'"
    ).fetchone()[0] == "8時だョ！全員集合（TBS, 1969–1985）"


def test_jlpt_joins_to_word_table(conn):
    # Every JLPT word with kanji must resolve in the word table via
    # jmdict_id = ent_seq; only kana-only words (skipped by the word table)
    # stay unresolved.
    total = conn.execute(
        "SELECT COUNT(*) FROM jlpt_word WHERE jmdict_id IS NOT NULL"
    ).fetchone()[0]
    joined = conn.execute(
        "SELECT COUNT(*) FROM jlpt_word j JOIN word w ON w.ent_seq = j.jmdict_id"
    ).fetchone()[0]
    assert total >= 7700
    assert total - joined <= 700  # kana-only words (アパート, カメラ, ...)
    # Spot check through the contract views: 食べる is an N5 word in the table.
    row = conn.execute(
        "SELECT j.level FROM jlpt_words j JOIN word w ON w.ent_seq = j.jmdict_id"
        " WHERE j.word = '食べる' AND w.surface = '食べる'"
    ).fetchone()
    assert row is not None and row[0] == 5
