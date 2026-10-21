# tangobon (語本)

"the word book" — the word/sentence layer for kanjifuda.

tangobon converts two dated EDRDG snapshots into a single SQLite database
with a small set of contract views for the app:

- **JMdict_e_examp.gz** — words: surface (`keb`), dictionary reading,
  primary English gloss, and the link to Tanaka example sentences.
- **examples.utf.gz** — Tanaka-style bilingual sentence pairs (Tatoeba-fed).

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

## Build

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/).

    make build     # → output/tangobon.sqlite
    make stats     # row counts
    make test      # pytest (one build, contract-view checks)

## Schema and contract views

Tables: `word`, `word_kanji`, `word_example`, `sentence`, `sentence_token`.
`PRAGMA user_version` is 1003 and must be bumped on any schema change.

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

Row order in all views is incidental; never assume it.

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
