"""Guard a semantic token split without changing other lexical occurrences."""
import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tangobon.builder import _SCHEMA
from tangobon.reviewed_content import apply_reviewed_content

DATA = Path(__file__).resolve().parents[1] / 'data'
SPEC = json.loads((DATA / 'reviewed_tokenizations.json').read_text())
ITEM = SPEC['tokenizations'][0]
FIELDS = ('lemma', 'form', 'reading', 'entry_ref')


def fixture():
    conn = sqlite3.connect(':memory:')
    conn.executescript(_SCHEMA)
    for ident, (ref, spelling) in enumerate([('1577100', '何'), ('2080990', '奇')], 1):
        conn.execute('INSERT INTO word VALUES(?,?,?,NULL,?,NULL)', (ident, ref, spelling, 'fixture'))
    for item in SPEC['tokenizations']:
        conn.execute('INSERT INTO sentence VALUES(?,?,?,?)', (item['sent_id'], item['sent_id'], item['expected_text'], item['expected_translation']))
        conn.executemany('INSERT INTO sentence_token VALUES(?,?,?,?,?,?)',
                         [(item['sent_id'], pos, *(t[k] for k in FIELDS)) for pos, t in enumerate(item['expected_tokens'])])
    conn.execute("INSERT INTO sentence VALUES('other','other','何かが動いた。','Something moved.')")
    conn.execute("INSERT INTO sentence_token VALUES('other',0,'何か','何か','なにか','1188270')")
    conn.execute("INSERT INTO word_example VALUES(1,'186714')")
    return conn


def test_interrogative_split_is_exact_and_does_not_change_lexical_something():
    conn = fixture()
    sentences = conn.execute('SELECT * FROM sentence ORDER BY sent_id').fetchall()
    links = conn.execute('SELECT * FROM word_example').fetchall()
    stats = {'tokens': 6}
    apply_reviewed_content(conn, DATA / 'reviewed_tokenizations.json', stats)
    for item in SPEC['tokenizations']:
        assert conn.execute('SELECT lemma,form,reading,entry_ref FROM sentence_token WHERE sent_id=? ORDER BY pos', (item['sent_id'],)).fetchall() == [tuple(t[k] for k in FIELDS) for t in item['tokens']]
    assert conn.execute("SELECT lemma,form,reading,entry_ref FROM sentence_token WHERE sent_id='other'").fetchone() == ('何か', '何か', 'なにか', '1188270')
    assert conn.execute('SELECT * FROM sentence ORDER BY sent_id').fetchall() == sentences
    assert conn.execute('SELECT * FROM word_example').fetchall() == links
    assert stats['tokens'] == 6 + sum(len(x['tokens']) - len(x['expected_tokens']) for x in SPEC['tokenizations'])


@pytest.mark.parametrize('defect', ['stale_text', 'stale_tokens', 'unknown_entry', 'changed_surface', 'unapproved', 'late_failure'])
def test_tokenization_validation_fails_closed(tmp_path, defect):
    spec = copy.deepcopy(SPEC)
    item = spec['tokenizations'][0]
    if defect == 'stale_text':
        item['expected_text'] = 'Changed upstream'
    elif defect == 'stale_tokens':
        item['expected_tokens'][-1]['reading'] = 'なにか'
    elif defect == 'unknown_entry':
        item['tokens'][-2]['entry_ref'] = 'missing'
    elif defect == 'changed_surface':
        item['tokens'][-1]['form'] = 'かな'
    elif defect == 'late_failure':
        second = copy.deepcopy(item)
        second['review_id'] = 'stale-second-review'
        second['expected_text'] = 'Changed upstream'
        spec['tokenizations'].append(second)
    review = {'items': [{'id': x['review_id'], 'status': 'answered', 'tokenization': copy.deepcopy(x)} for x in spec['tokenizations']]}
    if defect == 'unapproved':
        item['tokens'][-2]['reading'] = 'なん'
    review_path = tmp_path / 'review.json'
    review_path.write_text(json.dumps(review))
    spec['source_review'] = str(review_path)
    spec['review_sha256'] = hashlib.sha256(review_path.read_bytes()).hexdigest()
    path = tmp_path / 'overlay.json'
    path.write_text(json.dumps(spec))
    conn = fixture()
    old = conn.execute('SELECT * FROM sentence_token ORDER BY sent_id,pos').fetchall()
    stats = {'tokens': 6}
    with pytest.raises(ValueError):
        apply_reviewed_content(conn, path, stats)
    assert conn.execute('SELECT * FROM sentence_token ORDER BY sent_id,pos').fetchall() == old
    assert stats == {'tokens': 6}
