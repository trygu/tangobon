.PHONY: sync build stats test clean

sync:
	uv sync

build:
	uv run tangobon build \
		--input-jmdict data/JMdict_e_examp.gz \
		--input-examples data/examples.utf.gz \
		--input-jlpt-dir data/ \
		--db output/tangobon.sqlite

stats:
	uv run tangobon stats --db output/tangobon.sqlite

test:
	uv run pytest

clean:
	rm -rf output .venv
