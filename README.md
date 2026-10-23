# tangobon (語本)

"the word book" — the word/sentence layer for kanjifuda.

tangobon converts dated snapshots into a single SQLite database with a
small set of contract views for the app:

- **JMdict_e_examp.gz** — words: surface (`keb`), dictionary reading,
  primary English gloss, and the link to Tanaka example sentences.
- **examples.utf.gz** — Tanaka-style bilingual sentence pairs (Tatoeba-fed).
- **openjlpt-vocab-n5..n1.json** — the OpenJLPT vocabulary lists: a JLPT
  level for each word (see "JLPT levels" below).
- **bonus/*.json** — hand-curated bonus phrase sets (currently
  `drifters-80s`: 1980s ザ・ドリフターズ catchphrases with furigana, see
  "Bonus phrases" below).

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
- `bonus/drifters-catchphrases-2026-10-23.json` — hand-curated catchphrase
  set, not a snapshot: each phrase verified against ja.wikipedia
  (『8時だョ!全員集合』, "流行語（出演者別）" section) and the official TBS
  page, with the URL recorded per phrase. Text-only quotation of short
  catchphrases; the personality-rights considerations are recorded in the
  kanjifuda design note
  `docs/kanjifuda/docs/design-feedback-2026-10-23-drifters-easter-egg.md`
  (public release is a separate gated content resource).

## Build

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/).

    make build     # → output/tangobon.sqlite
    make stats     # row counts
    make test      # pytest (one build, contract-view checks)

Builds pass `--input-jlpt-dir data` and `--input-bonus-dir data/bonus`
(the defaults), so the JLPT level table is loaded whenever the
`openjlpt-vocab-n*.json` snapshots are present and the bonus phrase sets
whenever `data/bonus/*.json` files exist.

## Schema and contract views

Tables: `word`, `word_kanji`, `word_example`, `sentence`, `sentence_token`,
`jlpt_word`, `bonus_phrase`. `PRAGMA user_version` is 1005 and must be
bumped on any schema change.

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
- `bonus_phrases(phrase_id, set_name, era, speaker, phrase, reading, show,
  context, source, verified)` — curated bonus phrase sets (see below).

Row order in all views is incidental; never assume it.

## Bonus phrases

`bonus_phrases` carries hand-curated phrase sets for app-side bonus
content (easter eggs). One JSON file in `data/bonus/` per set. The current
set is `drifters-80s` (curated 2026-10-23, 14 phrases): catchphrases of the
1980s ザ・ドリフターズ five (いかりや長介, 加藤茶, 高木ブー, 仲本工事,
志村けん) from 『8時だョ!全員集合』 (TBS, 1969–1985) and
『ドリフ大爆笑』, each with furigana and its verification source. Notes
that matter for consumers:

- **Kanji-only**: kana-only lines were excluded at curation time —
  kanjifuda consumes kanji words and sentences only. Member coverage
  reflects that (仲本工事 and 高木ブー currently have no kanji-bearing
  personal catchphrase in the pool).
- `verified` is 1 for phrases documented in the cited `source`, 0 for
  unverified leads; all rows in the current set are verified.
- This is content data, not pedagogical review: whether and where the app
  shows a phrase is a kanjifuda design decision.

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
