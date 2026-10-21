"""Streaming JMdict + Tanaka snapshot → SQLite builder.

Parses the two dated EDRDG snapshots (``JMdict_e_examp.gz`` and
``examples.utf.gz``) using only the Python standard library and builds a
flat word/sentence database with two contract views for the app:

  * ``kanji_words(kanji, surface, reading, gloss, ent_seq)``
  * ``word_sentences(word_id, surface, sent_id, text, translation)``

Reading convention:

  * A ``k_ele`` surface keeps its ``k_read`` when present; otherwise the
    entry's unique unambiguous kana reading (a single ``r_ele`` without
    ``re_restr``) is used. Ambiguous or restricted readings stay NULL.

Sentence join:

  * ``examples.utf`` ``#ID=<tatoeba_id>_<tanaka_id>``: the second part is the
    Tanaka entry number referenced by JMdict ``<ex_srce exsrc_type="tat">``.
  * ``examples.utf`` ``B:`` lines (morphological analysis) are not stored.
  * A: lines without a ``#ID=`` tag cannot be joined and are skipped.
"""

from __future__ import annotations

import gzip
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

USER_VERSION = 1001

# CJK ideographs (main block, Extension A, compatibility block). Surfaces
# outside these ranges are treated as non-kanji.
KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
A_LINE_RE = re.compile(r"^A:\s(.*?)\t(.*)$")
ID_TAG_RE = re.compile(r"#ID=(\S+)$")

_COMMIT_EVERY = 20000

_SCHEMA = """
CREATE TABLE word(
    word_id INTEGER PRIMARY KEY,
    ent_seq TEXT NOT NULL,
    surface TEXT NOT NULL,
    reading TEXT,
    gloss TEXT NOT NULL,
    UNIQUE(ent_seq, surface)
);
CREATE INDEX idx_word_surface ON word(surface);

CREATE TABLE word_kanji(
    word_id INTEGER NOT NULL REFERENCES word(word_id),
    kanji TEXT NOT NULL,
    PRIMARY KEY(word_id, kanji)
);
CREATE INDEX idx_word_kanji_kanji ON word_kanji(kanji);

CREATE TABLE word_example(
    word_id INTEGER NOT NULL REFERENCES word(word_id),
    tanaka_entry TEXT NOT NULL,
    PRIMARY KEY(word_id, tanaka_entry)
);

CREATE TABLE sentence(
    sent_id TEXT PRIMARY KEY,  -- full #ID, "<tatoeba_id>_<tanaka_id>"
    tanaka_entry TEXT NOT NULL,  -- second part of #ID
    text TEXT NOT NULL,
    translation TEXT NOT NULL
);
CREATE INDEX idx_sentence_entry ON sentence(tanaka_entry);

CREATE VIEW kanji_words AS
SELECT wk.kanji AS kanji,
       w.surface AS surface,
       w.reading AS reading,
       w.gloss AS gloss,
       w.ent_seq AS ent_seq
FROM word_kanji AS wk
JOIN word AS w ON w.word_id = wk.word_id;

CREATE VIEW word_sentences AS
SELECT w.word_id AS word_id,
       w.surface AS surface,
       s.sent_id AS sent_id,
       s.text AS text,
       s.translation AS translation
FROM word_example AS we
JOIN word AS w ON w.word_id = we.word_id
JOIN sentence AS s ON s.tanaka_entry = we.tanaka_entry;
"""


def build_sqlite(
    jmdict_path: str | Path, examples_path: str | Path, db_path: str | Path
) -> dict:
    """Build the word/sentence database from the two dated snapshots."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    stats = {
        "entries": 0,
        "words": 0,
        "words_with_examples": 0,
        "sentences": 0,
        "user_version": USER_VERSION,
    }
    _build_words(conn, jmdict_path, stats)
    _build_sentences(conn, examples_path, stats)
    conn.commit()

    stats["words"] = conn.execute("SELECT COUNT(*) FROM word").fetchone()[0]
    stats["sentences"] = conn.execute("SELECT COUNT(*) FROM sentence").fetchone()[0]

    conn.execute(f"PRAGMA user_version = {USER_VERSION}")
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    return stats


def _build_words(conn: sqlite3.Connection, jmdict_path: str | Path, stats: dict) -> None:
    ent_seq: str | None = None
    surfaces: list[tuple[str, str | None]] = []
    kana_only: list[str] = []  # r_ele reb values without re_restr
    primary_gloss: str | None = None
    tanaka_entries: list[str] = []
    entries = 0

    with gzip.open(jmdict_path, "rb") as f:
        for event, elem in ET.iterparse(f, events=("start", "end")):
            tag = elem.tag
            if event == "start":
                if tag == "entry":
                    ent_seq = None
                    surfaces = []
                    kana_only = []
                    primary_gloss = None
                    tanaka_entries = []
                continue

            if tag == "ent_seq":
                ent_seq = (elem.text or "").strip()
            elif tag == "k_ele":
                keb = (elem.findtext("keb") or "").strip()
                if keb:
                    kread = (elem.findtext("k_read") or "").strip()
                    surfaces.append((keb, kread or None))
            elif tag == "r_ele":
                reb = (elem.findtext("reb") or "").strip()
                if reb and elem.findtext("re_restr") is None:
                    kana_only.append(reb)
            elif tag == "gloss":
                if primary_gloss is None:
                    text = (elem.text or "").strip()
                    if text:
                        primary_gloss = text
            elif tag == "example":
                srce = elem.find("ex_srce")
                if srce is not None and srce.get("exsrc_type") == "tat":
                    text = (srce.text or "").strip()
                    if text:
                        tanaka_entries.append(text)
            elif tag == "entry":
                # Entry-level kana: unique and unambiguous only.
                entry_kana = kana_only[0] if len(kana_only) == 1 else None
                if ent_seq and surfaces and primary_gloss:
                    for surface, reading in surfaces:
                        cur = conn.execute(
                            "INSERT INTO word(ent_seq, surface, reading, gloss)"
                            " VALUES(?,?,?,?)",
                            (ent_seq, surface, reading or entry_kana, primary_gloss),
                        )
                        word_id = cur.lastrowid
                        for ch in set(KANJI_RE.findall(surface)):
                            conn.execute(
                                "INSERT INTO word_kanji(word_id, kanji) VALUES(?,?)",
                                (word_id, ch),
                            )
                        if tanaka_entries:
                            stats["words_with_examples"] += 1
                        for t in tanaka_entries:
                            conn.execute(
                                "INSERT OR IGNORE INTO word_example(word_id,"
                                " tanaka_entry) VALUES(?,?)",
                                (word_id, t),
                            )
                entries += 1
                if entries % _COMMIT_EVERY == 0:
                    conn.commit()
                elem.clear()
    stats["entries"] = entries


def _build_sentences(conn: sqlite3.Connection, examples_path: str | Path, stats: dict) -> None:
    with gzip.open(examples_path, "rt", encoding="utf-8") as f:
        for line in f:
            m = A_LINE_RE.match(line.rstrip("\n"))
            if not m:
                continue
            jp = m.group(1).strip()
            rest = m.group(2)
            idm = ID_TAG_RE.search(rest)
            if idm is None:
                continue  # unnumbered lines cannot be joined to JMdict
            sent_id = idm.group(1)
            translation = rest[: idm.start()].strip()
            if not jp or not translation:
                continue
            # #ID=<tatoeba_id>_<tanaka_id>: the second part is the Tanaka
            # entry number referenced by JMdict <ex_srce exsrc_type="tat">.
            tanaka_entry = sent_id.split("_", 1)[1] if "_" in sent_id else None
            if tanaka_entry is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO sentence(sent_id, tanaka_entry,"
                " text, translation) VALUES(?,?,?,?)",
                (sent_id, tanaka_entry, jp, translation),
            )
        conn.commit()
