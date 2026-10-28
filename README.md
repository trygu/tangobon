# tangobon (語本)

![Build Database](https://github.com/trygu/tangobon/actions/workflows/build-database.yml/badge.svg)

"the word book" — the word/sentence layer for kanji learning applications.

tangobon converts dated snapshots into a single SQLite database with a
small set of contract views for consuming applications:

- **JMdict_e_examp.gz** — words: surface (`keb`), dictionary reading,
  primary English gloss, and the link to Tanaka example sentences.
- **examples.utf.gz** — Tanaka-style bilingual sentence pairs (Tatoeba-fed).
- **openjlpt-vocab-n5..n1.json** — the OpenJLPT vocabulary lists: a JLPT
  level for each word (see "JLPT levels" below).
- **bonus/*.json** — hand-curated bonus phrase sets (currently
  `drifters-80s`: 1980s ザ・ドリフターズ catchphrases with furigana, see
  "Bonus phrases" below).

The character layer (kanji, readings, strokes, JLPT estimates) lives in the
sibling project [kanjibon](https://github.com/trygu/kanjibon). The two
projects are the character and word/sentence halves of one data
foundation: tangobon words link back to kanjibon kanji on the literal.

## Data provenance

`data/` holds the exact snapshots this project builds from, with SHA-256
checksums in `data/CHECKSUMS` and fetch metadata in `data/SNAPSHOTS.txt`.
Builds use these files, not the live network.

- `JMdict_e_examp.gz` — EDRDG, CC BY-SA 4.0 (snapshot 2026-10-21).
- `examples.utf.gz` — EDRDG distribution of the Tanaka sentence collection,
  which is Tatoeba-fed; sentences are subject to the Tatoeba/EDRDG
  redistribution terms — read the EDRDG distribution notes that accompany
  the snapshot before redistributing the database.
- `openjlpt-vocab-n5..n1.json` + `openjlpt-meta.json` — the [OpenJLPT]
  (https://github.com/evanclan/OpenJLPT) vocabulary lists, CC BY-SA 4.0
  (snapshot of commit `0d1d341`, fetched 2026-10-21). Attribution per
  OpenJLPT's NOTICE: it uses JMdict and KANJIDIC2 (EDRDG), Jonathan
  Waller's JLPT lists (CC BY), and Tatoeba.
- `bonus/drifters-catchphrases-2026-10-23.json` — hand-curated catchphrase
  set, not a snapshot: each phrase verified against ja.wikipedia
  (『8時だョ!全員集合』, "流行語（出演者別）" section) and the official TBS
  page, with the URL recorded per phrase. Text-only quotation of short
  catchphrases, each kept with its verification source; use beyond this
  dataset (audio, imagery, standalone publication) requires a separate
  rights review.
- `reading_supplement.tsv` — project-owned curated readings, not a
  snapshot: each row fills one `word.reading` that the JMdict rule leaves
  NULL (multi-reading entries), with per-row evidence comments. Seeded
  2026-10-24 (150 priority-evidence picks) plus 21 contested readings
  chosen in a user review session the same day (日本→にほん, 今日→きょう…).
  Contested readings without a user pick are never added.

## Build

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/).

    make build     # → output/tangobon.sqlite
    make stats     # row counts
    make test      # pytest (one build, contract-view checks)

Builds pass `--input-jlpt-dir data`, `--input-bonus-dir data/bonus` and
`--input-reading-supplement data/reading_supplement.tsv` (the defaults),
so the JLPT level table is loaded whenever the `openjlpt-vocab-n*.json`
snapshots are present, the bonus phrase sets whenever `data/bonus/*.json`
files exist, and the curated reading supplement whenever the TSV exists.

## Schema and contract views

`PRAGMA user_version` is 1007 and must be bumped on any schema change —
check it before relying on a specific layout.

### Tables

- **`word`** — one row per (JMdict entry, surface): `word_id`, `ent_seq`
  (the JMdict entry id), `surface`, `reading` (the dictionary reading;
  NULL when the entry has no unique unambiguous reading, unless filled by
  the curated supplement — see Data provenance), `gloss` (primary English
  gloss), `ke_pri` (space-joined JMdict frequency tags such as
  `ichi1 news1 nf01`, NULL when absent).
- **`word_kanji`** — the kanji a surface contains: `word_id`, `kanji`.
  This is the bridge to the kanjibon character layer.
- **`word_example`** — links a word to the Tanaka entries that carry its
  example sentences: `word_id`, `tanaka_entry`.
- **`sentence`** — one row per Tanaka example: `sent_id`
  (`"<tatoeba_id>_<tanaka_id>"`), `tanaka_entry`, `text` (Japanese),
  `translation` (English).
- **`sentence_token`** — the parsed `B:` morphological analysis of a
  sentence, one row per token: `sent_id`, `pos` (token position), `lemma`
  (base form), `form` (the form as written in the sentence), `reading` (the
  token's kana annotation — the *occurrence* reading, kept distinct from
  the dictionary reading), `entry_ref` (the `(#NNN)` dictionary reference:
  the JMdict `ent_seq` wherever it resolves).
- **`jlpt_word`** — `word`, `reading`, `level` (5 = N5, easiest … 1 = N1),
  `jmdict_id` (NULL for kana-only words), `openjlpt_id`. Primary key is the
  `(word, reading)` pair.
- **`bonus_phrase`** — curated bonus phrases: `phrase_id`, `set_name`,
  `era`, `speaker`, `phrase`, `reading` (space-separated furigana), `show`
  (show of origin), `context`, `source` (what the phrase was verified
  against), `verified` (1 = documented in `source`).

### Contract views (what consumers may rely on)

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

`bonus_phrases` carries hand-curated phrase sets for consumer-side bonus
content (e.g. easter eggs). One JSON file in `data/bonus/` per set. The current
set is `drifters-80s` (curated 2026-10-23, 14 phrases): catchphrases of the
1980s ザ・ドリフターズ five (いかりや長介, 加藤茶, 高木ブー, 仲本工事,
志村けん) from 『8時だョ!全員集合』 (TBS, 1969–1985) and
『ドリフ大爆笑』, each with furigana and its verification source. Notes
that matter for consumers:

- **Kanji-only**: kana-only lines were excluded at curation time — this
  project stores kanji-bearing words and sentences only. Member coverage
  reflects that (仲本工事 and 高木ブー currently have no kanji-bearing
  personal catchphrase in the pool).
- `verified` is 1 for phrases documented in the cited `source`, 0 for
  unverified leads; all rows in the current set are verified.
- This is content data, not pedagogical review: whether and where a
  consuming app shows a phrase is a consumer decision.

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
  Pedagogical review of words/sentences for a specific kanji is left to the
  consuming project, built on top of these views.

## Example queries

```sql
-- All words containing a given kanji, as the dictionary ranks them
SELECT surface, reading, gloss, ke_pri
FROM kanji_words WHERE kanji = '学' ORDER BY ent_seq LIMIT 20;

-- Example sentences (Japanese + English) linked to one word
SELECT sent_id, text, translation
FROM word_sentences WHERE surface = '学生';

-- The morphological analysis of a sentence:
-- lemma vs. the form as written, with the occurrence reading
SELECT pos, lemma, form, reading, entry_ref
FROM sentence_tokens WHERE sent_id = '1660875_2312937' ORDER BY pos;

-- JLPT level of a word+reading pair (明日 is N5 as あした, N4 as あす)
SELECT word, reading, level FROM jlpt_words WHERE word = '明日';

-- Curated bonus phrases from one set
SELECT speaker, phrase, reading, show
FROM bonus_phrases WHERE set_name = 'drifters-80s';

-- Cross-project: attach the kanjibon database and join a kanji's words
-- to the kanji's JLPT estimate (open both in one connection)
--   ATTACH 'kanjidic2.sqlite' AS kb;
SELECT k.lvl, k.main_meaning, kw.surface, kw.reading, kw.gloss
FROM kanji_words kw
JOIN kb.kanji_seed k ON k.literal = kw.kanji
WHERE kw.kanji = '雨' ORDER BY k.lvl;
```
# Reviewed sentence content

`make build` applies `data/reviewed_content.json` after the pinned snapshots and
reading supplement. The exact source review is retained under `data/reviews/`
and verified by SHA-256; all 25 approved answers must match their final Japanese,
English and occurrence reading. This adds 23 stable `reviewed:` sentence IDs,
corrects two existing English/token pairs, and leaves dictionary readings intact.
An approved occurrence does not choose a global default for an ambiguous word.
It does not alter the upstream snapshots. Schema1006 adds the lexical contracts
below; the original sentence identities remain unchanged.

Every new target has exactly one occurrence, an exact dictionary entry and kana
reading, and ordered context tokens covering every kanji. Context transcription
is explicit dictionary-bound enrichment, not an additional human linguistic
review. Stale corrections, conflicting bindings and incomplete annotations fail
the editorial pass atomically. `uv run pytest tests/test_reviewed_content.py`
checks actual snapshot imports plus rejected malformed overlays and rollback.

The N4 batch is `data/reviewed_n4_content.json`, backed by the normalized N4
review and original mixed submission under `data/reviews/`. `make build` applies
N5 then N4; `--input-reviewed-content` is repeatable for explicit batch selection.
The supplied revised N5 answers are retained for provenance but are not imported.
CR026's approved normalization is 回らない/まわらない, with dictionary lemma
回る/まわる. Target form/reading fields also preserve 進んでいる/すすんでいる
separately from 進む/すすむ. All dictionary defaults remain unchanged.

The N3 batch is `data/reviewed_n3_content.json`: 161 sentence pairs, CR050–CR210.
`make build` applies N5, N4, then N3 (208 new reviewed sentences in total).
The unchanged complete submission and normalized applied answers are retained
under `data/reviews/`; hashes distinguish source from application. Twenty
authorized shortened sentences fit the existing 26-character app limit. CR199
uses the approved single-occurrence 粒 replacement. Seven changed targets are
rebound to their actual written forms/readings; counters retain their dictionary
lemma separately from the full occurrence. Context readings are agent
transcriptions, not a claim of another human review.

`uv run pytest tests/test_reviewed_n3.py` verifies the real snapshot import,
exact occurrences, previous batches and unchanged dictionary defaults. The app
also needs exact verified irregular-reading breakdowns; import success alone
does not prove selectable exercises or safe ruby. The proposed 68-character
N3→N1 move was withdrawn and is not encoded here.

## Verified occurrence contract (schema1006)

`verified_occurrences` exposes `sent_id, entry_ref, lemma, lemma_reading, form,
reading, provenance_sha256`. `occurrence_reading_parts` exposes that exact
occurrence identity plus `pos, written_part, reading_part, kind`. The ordered
parts must concatenate to the complete written form and occurrence reading.
The 22 nontrivial N3 breakdowns are input data, not application source code.

The N2 batch is `data/reviewed_n2_content.json`: 141 approved pairs covering
146 focus-kanji paths (CR131–CR271, distinct N2 sentence identities). Both
`make build` and the default CLI include it. Original submitted bytes are kept
under `data/reviews/`; normalized review records explicitly use corrected pairs
where supplied and rebind changed occurrence forms/readings. N2 sentence text
is at most 23 characters; this does not change consuming applications' generic
length policies. `tests/test_reviewed_n2.py` checks prior batches, exact target
evidence and the transitive 慰める / rainbow 虹 entry bindings. No character
level mapping or reference-only policy is changed by this batch.

These contracts record lexical evidence only. They carry no focus-character
curriculum, learner level, fallback permission or reviewer-specific rule.
Consuming apps own pedagogical suitability. IDs are opaque join keys; changing
a reviewer's name or ID spelling must not change lexical validity or selection.
The provenance digest links evidence to retained review material without granting
runtime privileges. `tests/test_verified_occurrences.py` checks opaque IDs,
changed reviewer metadata, exact-entry binding and atomic rejection of malformed
parts. Import success alone does not establish lesson suitability.
# Quotation sentence integration (26 October 2026)

`data/quoted_content.json` prepares 12 of the existing Drifters source quotations
as ordinary `word_sentences`, `sentence_tokens` and `verified_occurrences` rows.
It uses the existing generic editorial importer and exact dictionary entries;
there is no source-name branch or app curriculum in the pipeline. Both `make
build` and the default CLI build include this batch and the N5/N4/N3 batches.

`data/reviews/drifters-lexical-2026-10-26.json` records source attribution,
translations, lexical preparation and exclusions. This is agent preparation
of the user-selected quotations, not a human linguistic or rights sign-off.
The original 14 quotations remain; bath-command reading annotations were corrected
on26 October, with the prior source hash and correction history retained in the
lexical preparation record. Two repeated-target
phrases are excluded from quiz occurrence preparation; the long ending chant
is available lexically but remains subject to the app's ordinary length limit.
Pedagogical approvals and priority remain in the consuming app's catalog.


## Position-bound contextual readings (schema1007)

`sentence_token_readings` extends raw tokens with full sentence text, UTF-16
start/length, resolution status, nullable occurrence reading, bindings_json,
provenance_sha256 and evidence_kind. Identity is (sent_id,pos). Raw corpus
annotations stay separate: they may be lemma readings, not occurrence readings.
Resolution runs after overlays, using pinned JMdict spelling/reading restrictions
and sense POS. Supported inflections live in the data builder; there is no
standalone-form shortcut. Ambiguous/unsupported/unbound/unaligned rows carry no
resolved reading. Compatible corpus annotations are distinguished from reviewed
positional/target evidence; compatibility is not expert linguistic acceptance.

`context_dictionary_readings` exposes supporting entry/spelling/lemma-reading
pairs and source identity. Multiple entries with the same occurrence reading
retain all bindings. data/context_reading_reviews.json records complete positional
reviews; sentence/token/dictionary identity is validated and conflicting reviews
fail the build. This is lexical evidence, not curriculum approval.

The small data/context_named_entities.json extract retains12 exact JMnedict
entries needed by existing reviewed sentences (田中/豊能), including alternative
readings, official source URL and snapshot hash. Names use jmnedict: identifiers;
source annotations disambiguate them. JMnedict is an EDRDG dictionary and its
licence/attribution requirements apply. Builds use only pinned local inputs.
Approved N2/N3 Japanese/English pairs stay unchanged. Some authored context tokens
are segmented/rebound correctly (三/十/度,旅行/中,面接/用,お腹,ご飯).

Consumers require resolved status, validate complete sentence identity and exact
spans, and omit the quiz target. Missing evidence is a coverage gap, never a
reason to use an unrelated pronunciation. Target-side reading derivation in a
consumer is outside this contextual-reading migration.

Search-only kana forms remain in `context_dictionary_readings` with their
`search_only` flag. They are excluded from automatic standard-display candidates,
not declared impossible; explicit compatible source or reviewed evidence can select
them. Direct dictionary lemma entries constrain resolution before inverse morphology,
so a noun such as 回 cannot acquire an unrelated verb-stem reading from 回る.
A nominal genitive の preserves its bound noun/pronoun/counter reading. A known
invalid binding can be recorded as `unresolved_binding`; it stays without ruby
until properly corrected and cannot silently fall back to dictionary guessing.

### Reviewed sentence supersession

An editorial sentence may include `supersedes: {sent_id, text, translation}`,
matched exactly against its hash-verified source review and the original corpus
pair. The build retires all word/example links to that old pair and adds the
replacement under a new reviewed identity. Original sentence/token rows remain
for historical encounters; new selection through `word_sentences` cannot return
the rejected pair. Validation and retirement share the overlay savepoint, so a
stale final item rolls back earlier changes. No schema or runtime policy change.
The 27 October 2026 sentence-quality batch corrects four B32 pairs (夕飯, 洗濯,
乗客 and figurative 畑); its provenance is in `data/reviews/`.

Normalized dictionary bindings aggregate `search_only` deterministically: a
binding is search-only only if every compatible attestation of the same entry,
spelling and normalized reading is search-only. This prevents rebuilds from
flipping metadata based on set iteration order when kana variants normalize to
the same reading. No spellings, entries or pronunciations are merged across keys.

### Reviewed tokenization repairs

`data/reviewed_tokenizations.json`, when present beside the dictionary snapshot,
uses the same hash-verified editorial overlay and is applied before positional
context readings in every build entry point. Each repair guards the exact
sentence/translation and complete ordered source token snapshot. Replacement
forms must preserve written content and alignment; changed kanji tokens require
an explicit dictionary entry. The overlay is atomic, including token statistics.
The 28 October repair splits only the interrogative 何 + か in the reviewed fire
question. Lexical 何か (“something”) elsewhere is unchanged. Source snapshot files
are never edited; the corrected built tokens and positional review retain the
same sentence identity. This adds no schema or app runtime rule.
