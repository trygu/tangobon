.PHONY: sync build stats test clean

sync:
	uv sync

build:
	uv run tangobon build \
		--input-jmdict data/JMdict_e_examp.gz \
		--input-examples data/examples.utf.gz \
		--input-jlpt-dir data/ \
		--input-bonus-dir data/bonus/ \
		--input-reading-supplement data/reading_supplement.tsv \
		--input-reviewed-content data/reviewed_content.json \
		--input-reviewed-content data/reviewed_n4_content.json \
		--input-reviewed-content data/reviewed_n3_content.json \
		--input-reviewed-content data/quoted_content.json \
		--db output/tangobon.sqlite

stats:
	uv run tangobon stats --db output/tangobon.sqlite

test:
	uv run pytest

clean:
	rm -rf output .venv
