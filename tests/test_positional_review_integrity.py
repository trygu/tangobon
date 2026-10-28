"""A review-file hash alone cannot authorize a different override payload."""
import copy
import gzip
import hashlib
import json
import sqlite3

import pytest
from tangobon.builder import _SCHEMA
from tangobon.context_readings import build_context_readings


def fixture(tmp_path):
    dictionary = tmp_path / 'dictionary.gz'
    with gzip.open(dictionary, 'wt') as stream:
        stream.write('<JMdict><entry><ent_seq>1</ent_seq><k_ele><keb>低い</keb></k_ele><r_ele><reb>ひくい</reb></r_ele><sense><pos>adjective (keiyoushi)</pos></sense></entry></JMdict>')
    conn = sqlite3.connect(':memory:')
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO sentence VALUES('s','s','低すぎる。','Too low.')")
    conn.execute("INSERT INTO sentence_token VALUES('s',0,'低い','低',NULL,NULL)")
    item = dict(sent_id='s',pos=0,text='低すぎる。',lemma='低い',form='低',entry_ref='1',spelling='低い',lemma_reading='ひくい',reading='ひく')
    approval = tmp_path / 'approval.json'
    approval.write_text(json.dumps({'schema_version':1,'approved_occurrences':[copy.deepcopy(item)]}))
    spec = dict(schema_version=2,occurrences=[item],review_sources=[dict(file=approval.name,sha256=hashlib.sha256(approval.read_bytes()).hexdigest())])
    return conn, dictionary, approval, spec


def write_spec(tmp_path, spec):
    path = tmp_path / 'overrides.json'
    path.write_text(json.dumps(spec))
    return path


def test_tampered_reading_cannot_borrow_another_approval(tmp_path):
    conn, dictionary, _, spec = fixture(tmp_path)
    spec['occurrences'][0]['reading'] = 'てい'
    with pytest.raises(ValueError, match='Unapproved contextual reading payload'):
        build_context_readings(conn, dictionary, write_spec(tmp_path, spec))


def test_exact_approved_payload_still_resolves(tmp_path):
    conn, dictionary, _, spec = fixture(tmp_path)
    build_context_readings(conn, dictionary, write_spec(tmp_path, spec))
    assert conn.execute('SELECT reading,status FROM sentence_token_readings').fetchone() == ('ひく','resolved')


@pytest.mark.parametrize('field,value', [
    ('entry_ref','other'), ('lemma_reading','てい'), ('text','different'),
    ('form','違'), ('lemma','違う'), ('rationale','unreviewed note'),
])
def test_other_payload_edits_are_rejected(tmp_path, field, value):
    conn, dictionary, _, spec = fixture(tmp_path)
    spec['occurrences'][0][field] = value
    with pytest.raises(ValueError, match='Unapproved contextual reading payload'):
        build_context_readings(conn, dictionary, write_spec(tmp_path, spec))
    assert conn.execute('SELECT count(*) FROM token_reading_evidence').fetchone()[0] == 0


@pytest.mark.parametrize('defect,match', [
    ('missing_source','Unapproved'), ('missing_approval','Unapproved'),
    ('duplicate_approval','Duplicate contextual reading approval'),
    ('unused_approval','Unused contextual reading approval'),
    ('duplicate_override','Duplicate contextual reading review position'),
    ('bad_hash','source hash mismatch'), ('old_spec','Unsupported contextual'),
    ('old_approval','Unsupported positional approval'),
])
def test_review_sources_fail_closed(tmp_path, defect, match):
    conn, dictionary, source, spec = fixture(tmp_path)
    review = json.loads(source.read_text())
    if defect == 'missing_source': spec['review_sources'] = []
    elif defect == 'missing_approval': review['approved_occurrences'] = []
    elif defect == 'duplicate_approval': review['approved_occurrences'] *= 2
    elif defect == 'unused_approval': spec['occurrences'] = []
    elif defect == 'duplicate_override': spec['occurrences'] *= 2
    elif defect == 'old_spec': spec['schema_version'] = 1
    elif defect == 'old_approval': review['schema_version'] = 0
    elif defect == 'bad_hash': spec['review_sources'][0]['sha256'] = '0'*64
    source.write_text(json.dumps(review))
    if defect != 'bad_hash' and spec['review_sources']:
        spec['review_sources'][0]['sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=match):
        build_context_readings(conn, dictionary, write_spec(tmp_path, spec))
    assert conn.execute('SELECT count(*) FROM token_reading_evidence').fetchone()[0] == 0
