# tangobon (語本)

"the word book" — the word/sentence layer for kanjifuda.

tangobon converts dated snapshots into a single SQLite database with a
small set of contract views for the app:

- **JMdict_e_examp.gz** — words: surface (`keb`), dictionary reading,
  primary English gloss, and the link to Tanaka example sentences.
- **examples.utf.gz** — Tanaka-style bilingual sentence pairs (Tatoeba-fed).
- **openjlpt-vocab-n5..n1.json** — the OpenJLPT vocabulary lists: a JLPT
  level for each word (see "JLPT levels" below).

The character layer (kanji, readings, strokes, JLPT estimates) lives in the
sibling project [kanjibon](https://github.com/trygu/kanjibon). tangobon is
the word/sentence counterpart, pinned alongside kanjibon from the kanjifuda
orchestration repository.

## Data provenance

`data/` holds the exact snapshots this project builds from, with SHA-256
checksums in `data/CHECKSUMS` and fetch metadata in `data/SNAPSHOTS.txt`.
Builds use these files, not the live network.

- `JMdict_e_examp.gz` — EDRDG, CC BY-SA 4.0 (snapshot 2026-10-21).
- `examples.utf.gz` — EDRDG distribution of the Tanaka sentence collection,
  which is Tatoeba-fed; sentences are subject to the Tatoeba/EDRDG
  redistribution terms recorded in the kanjifuda evidence register (E027).
- `openjlpt-vocab-n5..n1.json` + `openjlpt-meta.json` — the [OpenJLPT]
  (https://github.com/evanclan/OpenJLPT) vocabulary lists, CC BY-SA 4.0
  (snapshot of commit `0d1d341`, fetched 2026-10-21). Attribution per
  OpenJLPT's NOTICE: it uses JMdict and KANJIDIC2 (EDRDG), Jonathan
  Waller's JLPT lists (CC BY), and Tatoeba.

## Build

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/).

    make build     # → output/tangobon.sqlite
    make stats     # row counts
    make test      # pytest (one build, contract-view checks)

Builds pass `--input-jlpt-dir data` (the default), so the JLPT level table
is loaded whenever the `openjlpt-vocab-n*.json` snapshots are present.

## Schema and contract views

Tables: `word`, `word_kanji`, `word_example`, `sentence`, `sentence_token`,
`jlpt_word`. `PRAGMA user_version` is 1004 and must be bumped on any schema
change.

Contract views (what the app may rely on):

- `kanji_words(kanji, surface, reading, gloss, ke_pri, ent_seq)` — words
  containing the given kanji; `reading` is the dictionary reading and may be
  NULL; `ke_pri` carries the JMdict frequency tags (ichi1, news1, nf01, ...)
  space-joined, NULL when the surface has none — the dictionary's own
  importance markers for ranking candidate words per kanji.
- `word_sentences(word_id, surface, sent_id, text, translation)` — the
  example sentences linked to a word through its Tanaka entry.
- `sentence_tokens(sent_id, pos, lemma, form, reading, entry_ref)` — the
  parsed `B:` morphological analysis of a sentence: `lemma` is the base
  form, `form` the form as written in the sentence, `reading` the kana
  annotation (the occurrence reading, kept distinct from the dictionary
  reading), and `entry_ref` the `(#NNN)` dictionary reference, which is the
  JMdict `ent_seq` wherever it resolves.
- `jlpt_words(word, reading, level, jmdict_id, openjlpt_id)` — the JLPT
  level of a word (see below).

Row order in all views is incidental; never assume it.

## JLPT levels

`jlpt_words` maps a `(word, reading)` pair to a JLPT level, from the
OpenJLPT vocabulary lists (7,811 words). `level` is an integer with
`5` = N5 (easiest) and `1` = N1; a word "fits" a learner at level L when
`level >= L`. Notes that matter for consumers:

- **The level attaches to the `(word, reading)` pair, not the surface**:
  明日 is N5 as あした but N4 as あす.
- **The levels are estimates.** The Japan Foundation publishes no official
  vocabulary lists; the assignments are Jonathan Waller's community lists
  (the ones Jisho.org uses). They are a level-fit *filter input*, not a
  statement about any individual word.
- **Joining to the word table** is by `jmdict_id = word.ent_seq`. It is NULL
  for kana-only words (アパート, カメラ, ...), which the word table
  intentionally skips; every JLPT word that contains kanji joins.

## Scope decisions (what is deliberately not here)

- `r_ele` (kana-only) entries are skipped: the contract is kanji words.
- `examples.utf` `B:` lines are parsed into `sentence_token` rows; the raw
  `B:` text and the `[nn]` analysis flags are not stored.
- Tanaka's own lemma mapping can be suspect (e.g. 遭った analyzed under the
  会う entry); token evidence is a filter input for the consuming pipeline,
  not ground truth.
- Only the primary gloss (first gloss of the first sense) is kept.
- This is a **raw** word/sentence layer, not pedagogically reviewed content.
  Review of words/sentences for a specific kanji is a kanjifuda content-pack
  decision, made on top of these views.
