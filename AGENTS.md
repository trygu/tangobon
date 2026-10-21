# AGENTS.md — tangobon

Word/sentence layer for kanjifuda: JMdict + Tanaka snapshots → SQLite.

## Overview

- Character layer: the sibling project [kanjibon](https://github.com/trygu/kanjibon).
  This project is words and sentences only — do not add kanji data here.
- Inputs: dated EDRDG snapshots kept in `data/` with checksums; no network
  access at build time.

## Rules

- Standard library only. No runtime dependencies.
- Streaming parses; do not load whole snapshot files into memory.
- Schema changes require bumping `PRAGMA user_version` (currently 1003) and
  updating the tests.
- The contract views (`kanji_words`, `word_sentences`) are the app's
  interface; keep them stable. Extend, don't break.
- Re-fetching snapshots: update `data/CHECKSUMS` and `data/SNAPSHOTS.txt`,
  and record a dated note in the kanjifuda evidence register.
- Importing data into this database is not a review: pedagogical acceptance
  of words/sentences for a specific kanji is a kanjifuda content-pack
  decision.

## Tooling

- uv for the environment and lockfile; `make build`, `make stats`, `make test`.
- CI runs the tests and builds the database on push/PR
  (see `.github/workflows/build-database.yml`).
