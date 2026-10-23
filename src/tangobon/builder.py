"""Streaming JMdict + Tanaka snapshot → SQLite builder.

Parses the two dated EDRDG snapshots (``JMdict_e_examp.gz`` and
``examples.utf.gz``) using only the Python standard library and builds a
flat word/sentence database with two contract views for the app:

  * ``kanji_words(kanji, surface, reading, gloss, ke_pri, ent_seq)``
  * ``word_sentences(word_id, surface, sent_id, text, translation)``
  * ``sentence_tokens(sent_id, pos, lemma, form, reading, entry_ref)``
  * ``jlpt_words(word, reading, level, jmdict_id, openjlpt_id)``
  * ``bonus_phrases(phrase_id, set_name, era, speaker, phrase, reading,
    show, context, source, verified)``

Word importance:

  * ``ke_pri`` carries the surface's JMdict frequency tags (ichi1, news1,
    nf01, ...) space-joined and sorted; NULL when the surface has none.
    These are the dictionary's own importance markers and the basis for
    ranking candidate words per kanji.

Morphological tokens:

  * ``examples.utf`` ``B:`` lines are parsed into ``sentence_token`` rows:
    ``lemma`` (dictionary/base form), ``form`` (the form as written in the
    sentence — the ``{...}`` part, falling back to the lemma), ``reading``
    (the ``(kana)`` annotation) and ``entry_ref`` (the ``(#NNN)`` dictionary
    reference, which is the JMdict ``ent_seq`` where resolvable).
  * The raw ``B:`` text is not stored; the ``[nn]`` analysis flags are
    dropped. Note that Tanaka's own lemma mapping can be suspect (e.g.
    遭った analyzed under 会う), so token evidence is a filter input, not
    ground truth.

Reading convention:

  * A ``k_ele`` surface keeps its ``k_read`` when present; otherwise the
    entry's unique unambiguous kana reading (a single ``r_ele`` without
    ``re_restr``) is used. Ambiguous or restricted readings stay NULL.

Sentence join:

  * ``examples.utf`` ``#ID=<tatoeba_id>_<tanaka_id>``: the second part is the
    Tanaka entry number referenced by JMdict ``<ex_srce exsrc_type="tat">``.
  * ``examples.utf`` ``B:`` lines (morphological analysis) are not stored.
  * A: lines without a ``#ID=`` tag cannot be joined and are skipped.

JLPT levels:

  * ``openjlpt-vocab-n5.json`` ... ``openjlpt-vocab-n1.json`` (the OpenJLPT
    dataset, CC BY-SA 4.0; level assignments are Jonathan Waller's community
    lists — unofficial approximations, not an official JLPT syllabus) are
    loaded into ``jlpt_word``.
  * ``level`` is stored as an integer: 5 = N5 (easiest) ... 1 = N1. A word
    "fits" a learner at level L when ``level >= L`` (e.g. N4 and below is
    ``level >= 4``).
  * The level attaches to the ``(word, reading)`` pair, not the surface:
    明日 is N5 as あした but N4 as あす.
  * ``jmdict_id`` is the JMdict ``ent_seq`` where resolvable; it is NULL for
    kana-only words, which the word table intentionally skips, so every
    JLPT word with kanji joins ``word`` exactly.

Bonus phrases:

  * Hand-curated bonus phrase sets in ``data/bonus/*.json`` (one JSON file
    per set) are loaded into ``bonus_phrase``. The current set is
    ``drifters-80s``: 1980s ザ・ドリフターズ catchphrases with furigana,
    the kanjifuda word-view easter egg (curation record: kanjifuda design
    note design-feedback-2026-10-23-drifters-easter-egg.md).
  * Kanji-only by curation rule: kana-only lines are not in the sets because
    kanjifuda consumes kanji words and sentences only.
  * ``verified`` is 1 where the phrase is documented in the cited ``source``,
    0 for unverified leads.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

USER_VERSION = 1005

# CJK ideographs (main block, Extension A, compatibility block). Surfaces
# outside these ranges are treated as non-kanji.
KANJI_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
A_LINE_RE = re.compile(r"^A:\s(.*?)\t(.*)$")
ID_TAG_RE = re.compile(r"#ID=(\S+)$")
BRACE_RE = re.compile(r"\{([^}]*)\}")  # form as written in the sentence
REF_RE = re.compile(r"\(#(\d+)\)")  # dictionary reference (JMdict ent_seq)
PAREN_RE = re.compile(r"\(([^)]*)\)")  # kana reading annotation
FLAG_RE = re.compile(r"\[\d+\]")  # analysis flag (dropped)

_COMMIT_EVERY = 20000

_SCHEMA = """
CREATE TABLE word(
    word_id INTEGER PRIMARY KEY,
    ent_seq TEXT NOT NULL,
    surface TEXT NOT NULL,
    reading TEXT,
    gloss TEXT NOT NULL,
    ke_pri TEXT,  -- space-joined JMdict frequency tags (ichi1 news1 nf01 ...), NULL if none
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
       w.ke_pri AS ke_pri,
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

CREATE TABLE sentence_token(
    sent_id TEXT NOT NULL REFERENCES sentence(sent_id),
    pos INTEGER NOT NULL,
    lemma TEXT NOT NULL,  -- base form from the B: line
    form TEXT NOT NULL,   -- form as written in the sentence ({...} or lemma)
    reading TEXT,         -- (kana) annotation
    entry_ref TEXT,       -- (#NNN) reference: the JMdict ent_seq where resolvable
    PRIMARY KEY(sent_id, pos)
);
CREATE INDEX idx_token_ref ON sentence_token(entry_ref);

CREATE VIEW sentence_tokens AS
SELECT st.sent_id AS sent_id,
       st.pos AS pos,
       st.lemma AS lemma,
       st.form AS form,
       st.reading AS reading,
       st.entry_ref AS entry_ref
FROM sentence_token AS st;

CREATE TABLE jlpt_word(
    word TEXT NOT NULL,
    reading TEXT NOT NULL,
    level INTEGER NOT NULL,  -- 5 = N5 (easiest) ... 1 = N1; Waller community lists
    jmdict_id TEXT,          -- JMdict ent_seq where resolvable; NULL for kana-only words
    openjlpt_id TEXT,        -- stable id from the OpenJLPT dataset
    PRIMARY KEY(word, reading)
);
CREATE INDEX idx_jlpt_level ON jlpt_word(level);

CREATE VIEW jlpt_words AS
SELECT j.word AS word,
       j.reading AS reading,
       j.level AS level,
       j.jmdict_id AS jmdict_id,
       j.openjlpt_id AS openjlpt_id
FROM jlpt_word AS j;

CREATE TABLE bonus_phrase(
    phrase_id TEXT PRIMARY KEY,
    set_name TEXT NOT NULL,  -- bonus set the phrase belongs to (e.g. 'drifters-80s')
    era TEXT NOT NULL,
    speaker TEXT NOT NULL,
    phrase TEXT NOT NULL,
    reading TEXT NOT NULL,  -- furigana: space-separated readings
    show TEXT,              -- show of origin (the set's default unless overridden)
    context TEXT,
    source TEXT NOT NULL,   -- source the phrase was verified against
    verified INTEGER NOT NULL  -- 1 = documented in source; 0 = lead
);
CREATE INDEX idx_bonus_phrase_set ON bonus_phrase(set_name);

CREATE VIEW bonus_phrases AS
SELECT b.phrase_id AS phrase_id,
       b.set_name AS set_name,
       b.era AS era,
       b.speaker AS speaker,
       b.phrase AS phrase,
       b.reading AS reading,
       b.show AS show,
       b.context AS context,
       b.source AS source,
       b.verified AS verified
FROM bonus_phrase AS b;
"""


def build_sqlite(
    jmdict_path: str | Path,
    examples_path: str | Path,
    db_path: str | Path,
    jlpt_dir: str | Path | None = None,
    bonus_dir: str | Path | None = None,
) -> dict:
    """Build the word/sentence database from the dated snapshots.

    ``jlpt_dir`` (optional) holds the OpenJLPT vocabulary snapshots
    (``openjlpt-vocab-n5.json`` ... ``openjlpt-vocab-n1.json``); when given,
    the JLPT level table is loaded as well.

    ``bonus_dir`` (optional) holds the curated bonus phrase sets
    (``*.json``); when given, the bonus phrases are loaded as well.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()  # builds are reproducible from the snapshots
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)

    stats = {
        "entries": 0,
        "words": 0,
        "words_with_examples": 0,
        "sentences": 0,
        "jlpt_words": 0,
        "bonus_phrases": 0,
        "user_version": USER_VERSION,
    }
    _build_words(conn, jmdict_path, stats)
    _build_sentences(conn, examples_path, stats)
    _build_jlpt(conn, jlpt_dir, stats)
    _build_bonus(conn, bonus_dir, stats)
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
    surfaces: list[tuple[str, str | None, str | None]] = []
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
                    pri = " ".join(
                        sorted(
                            (t.text or "").strip()
                            for t in elem.findall("ke_pri")
                            if (t.text or "").strip()
                        )
                    )
                    surfaces.append((keb, kread or None, pri or None))
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
                    for surface, reading, ke_pri in surfaces:
                        cur = conn.execute(
                            "INSERT INTO word(ent_seq, surface, reading, gloss, ke_pri)"
                            " VALUES(?,?,?,?,?)",
                            (ent_seq, surface, reading or entry_kana, primary_gloss, ke_pri),
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


def _parse_b_line(bline: str) -> list[tuple[str, str, str | None, str | None]]:
    """Parse one B: line into (lemma, form, reading, entry_ref) tokens."""
    tokens = []
    for chunk in bline[3:].split():
        bm = BRACE_RE.search(chunk)
        form = bm.group(1).strip() if bm else None
        rest = BRACE_RE.sub("", chunk)
        fm = REF_RE.search(rest)
        entry_ref = fm.group(1) if fm else None
        rest = REF_RE.sub("", rest)
        rm = PAREN_RE.search(rest)
        reading = rm.group(1).strip() if rm else None
        rest = PAREN_RE.sub("", rest)
        lemma = FLAG_RE.sub("", rest).rstrip("~").strip()
        if not lemma and form is None:
            continue
        tokens.append((lemma, form if form is not None else lemma, reading, entry_ref))
    return tokens


def _build_sentences(conn: sqlite3.Connection, examples_path: str | Path, stats: dict) -> None:
    stats["sentences_with_tokens"] = 0
    stats["tokens"] = 0
    pending: str | None = None
    with gzip.open(examples_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("A:"):
                m = A_LINE_RE.match(line)
                if m:
                    jp = m.group(1).strip()
                    rest = m.group(2)
                    idm = ID_TAG_RE.search(rest)
                    if idm is not None:
                        sent_id = idm.group(1)
                        translation = rest[: idm.start()].strip()
                        # #ID=<tatoeba_id>_<tanaka_id>: the second part is the
                        # Tanaka entry number referenced by JMdict
                        # <ex_srce exsrc_type="tat">.
                        tanaka_entry = sent_id.split("_", 1)[1] if "_" in sent_id else None
                        if jp and translation and tanaka_entry is not None:
                            conn.execute(
                                "INSERT OR IGNORE INTO sentence(sent_id,"
                                " tanaka_entry, text, translation)"
                                " VALUES(?,?,?,?)",
                                (sent_id, tanaka_entry, jp, translation),
                            )
                            pending = sent_id
                continue
            if line.startswith("B:"):
                if pending is not None:
                    tokens = _parse_b_line(line)
                    if tokens:
                        conn.executemany(
                            "INSERT INTO sentence_token(sent_id, pos, lemma,"
                            " form, reading, entry_ref) VALUES(?,?,?,?,?,?)",
                            [
                                (pending, i, lemma, form, reading, ref)
                                for i, (lemma, form, reading, ref) in enumerate(tokens)
                            ],
                        )
                        stats["sentences_with_tokens"] += 1
                        stats["tokens"] += len(tokens)
                pending = None
                continue
            pending = None
        conn.commit()


def _build_jlpt(
    conn: sqlite3.Connection, jlpt_dir: str | Path | None, stats: dict
) -> None:
    """Load the OpenJLPT vocabulary snapshots into jlpt_word.

    The files are small (a few MB total), so they are read in full; the
    streaming rule applies to the large gz snapshots. ``level`` is stored
    as an integer with 5 = N5 (easiest) and 1 = N1.
    """
    if jlpt_dir is None:
        return
    jlpt_dir = Path(jlpt_dir)
    for level, name in ((5, "n5"), (4, "n4"), (3, "n3"), (2, "n2"), (1, "n1")):
        path = jlpt_dir / f"openjlpt-vocab-{name}.json"
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            conn.execute(
                "INSERT INTO jlpt_word(word, reading, level, jmdict_id,"
                " openjlpt_id) VALUES(?,?,?,?,?)",
                (
                    entry["word"],
                    entry["reading"],
                    level,
                    str(entry["jmdict_id"]) if entry.get("jmdict_id") else None,
                    entry.get("id"),
                ),
            )
            stats["jlpt_words"] += 1
    conn.commit()


def _build_bonus(
    conn: sqlite3.Connection, bonus_dir: str | Path | None, stats: dict
) -> None:
    """Load the curated bonus phrase sets into bonus_phrase.

    One JSON file per set in ``bonus_dir``: ``{"set", "era", "show"?,
    "phrases": [{"id", "speaker", "phrase", "reading", "show"?, "context"?,
    "source", "verified"?}, ...]}``. The files are small hand-curated
    content, so they are read in full; the streaming rule applies to the
    large gz snapshots. A phrase ``show`` falls back to the set's default.
    """
    if bonus_dir is None:
        return
    bonus_dir = Path(bonus_dir)
    if not bonus_dir.is_dir():
        return
    for path in sorted(bonus_dir.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        set_name = spec["set"]
        era = spec["era"]
        for p in spec["phrases"]:
            conn.execute(
                "INSERT INTO bonus_phrase(phrase_id, set_name, era, speaker,"
                " phrase, reading, show, context, source, verified)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    p["id"],
                    set_name,
                    era,
                    p["speaker"],
                    p["phrase"],
                    p["reading"],
                    p.get("show", spec.get("show")),
                    p.get("context"),
                    p["source"],
                    int(p.get("verified", 1)),
                ),
            )
            stats["bonus_phrases"] += 1
    conn.commit()
