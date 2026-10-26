"""Bath commands use 入る/はいる, not the transitive 入れる/いれる."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


def test_bath_commands_bind_the_hairu_imperative():
    source = json.loads((DATA / "bonus/drifters-catchphrases-2026-10-23.json").read_text())
    spec = json.loads((DATA / "quoted_content.json").read_text())
    for identity in ("group-ending-chant", "kato-furo-ireyo"):
        phrase = next(p for p in source["phrases"] if p["id"] == identity)
        assert "はいれよ" in phrase["reading"]
        sentence = next(s for s in spec["sentences"] if s["review_id"] == identity)
        tokens = [t for t in sentence["tokens"] if t["form"] == "入れよ"]
        assert tokens == [{"lemma": "入る", "form": "入れよ", "reading": "はいれよ", "entry_ref": "1465590"}]
