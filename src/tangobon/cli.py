"""tangobon command line interface."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .builder import USER_VERSION, build_sqlite

_TABLES = ("word", "word_kanji", "word_example", "sentence", "sentence_token", "jlpt_word", "bonus_phrase")


def _cmd_build(args: argparse.Namespace) -> None:
    jlpt_dir = Path(args.input_jlpt_dir) if args.input_jlpt_dir else None
    bonus_dir = Path(args.input_bonus_dir) if args.input_bonus_dir else None
    supplement = (
        Path(args.input_reading_supplement) if args.input_reading_supplement else None
    )
    stats = build_sqlite(
        Path(args.input_jmdict), Path(args.input_examples), Path(args.db),
        jlpt_dir, bonus_dir, supplement, args.input_reviewed_content,
    )
    print(f"Built {args.db}")
    for key in ("entries", "words", "words_with_examples", "sentences", "sentences_with_tokens", "tokens", "jlpt_words", "bonus_phrases", "supplemented_readings", "user_version"):
        print(f"  {key}: {stats[key]}")
    for key in ("reviewed_sentences", "reviewed_occurrence_repairs"):
        if key in stats:
            print(f"  {key}: {stats[key]}")


def _cmd_stats(args: argparse.Namespace) -> None:
    conn = sqlite3.connect(args.db)
    print(f"user_version: {conn.execute('PRAGMA user_version').fetchone()[0]} (expected {USER_VERSION})")
    for table in _TABLES:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n}")
    conn.close()


def app(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tangobon",
        description="JMdict + Tanaka word and sentence layer → SQLite",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build the SQLite database from the dated snapshots")
    b.add_argument("--input-jmdict", default="data/JMdict_e_examp.gz")
    b.add_argument("--input-examples", default="data/examples.utf.gz")
    b.add_argument(
        "--input-jlpt-dir", default="data",
        help="directory with the OpenJLPT vocabulary snapshots (openjlpt-vocab-n*.json)",
    )
    b.add_argument(
        "--input-bonus-dir", default="data/bonus",
        help="directory with the curated bonus phrase sets (*.json)",
    )
    b.add_argument(
        "--input-reading-supplement", default="data/reading_supplement.tsv",
        help="curated reading supplement (TSV); fills approved NULL readings",
    )
    b.add_argument("--db", default="output/tangobon.sqlite")
    b.add_argument("--input-reviewed-content", default="data/reviewed_content.json",
                   help="versioned, approved sentence and occurrence corrections")
    b.set_defaults(func=_cmd_build)

    s = sub.add_parser("stats", help="print row counts for a built database")
    s.add_argument("--db", default="output/tangobon.sqlite")
    s.set_defaults(func=_cmd_stats)

    args = parser.parse_args(argv)
    args.func(args)


def main() -> None:
    app()
