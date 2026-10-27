"""Reading candidates are entry/POS-bound; surface homographs cannot override them."""
import gzip
import json
import sqlite3
from pathlib import Path
import pytest
from tangobon.context_readings import Lexeme, dictionary_candidates, inflections, resolve, build_context_readings
from tangobon.builder import _SCHEMA


def lex(word,reading,pos,entry='entry'):
    return Lexeme(entry,word,reading,(pos,))


@pytest.mark.parametrize('word,reading,pos,form,expected',[
 ('若い','わかい','adjective (keiyoushi)','若く','わかく'),
 ('難しい','むずかしい','adjective (keiyoushi)','難し','むずかし'),
 ('観る','みる','Ichidan verb','観','み'),
 ('愛する','あいする','suru verb - special class','愛し','あいし'),
 ('引く','ひく',"Godan verb with 'ku' ending",'引き','ひき'),
 ('入り込む','はいりこむ',"Godan verb with 'mu' ending",'入り込み','はいりこみ'),
 ('来る','くる','Kuru verb - special class','来た','きた'),
 ('来る','くる','Kuru verb - special class','来よう','こよう'),
 ('来る','くる','Kuru verb - special class','来い','こい'),
])
def test_complete_pos_bound_forms(word,reading,pos,form,expected):
    assert inflections(lex(word,reading,pos)).get(form)==expected


def test_standalone_form_cannot_override_bound_lemma():
    candidates={'低い':(lex('低い','ひくい','adjective (keiyoushi)','adjective'),),
                '低':(lex('低','てい','noun','noun'),)}
    assert resolve(candidates,'低い','低') == ('resolved','ひく',[('adjective','低い','ひくい','ひく')])


def test_alternative_readings_stay_ambiguous_and_source_annotation_disambiguates():
    candidates={'低い':tuple(lex('低い',r,'adjective (keiyoushi)') for r in ['ひくい','ひっくい'])}
    assert resolve(candidates,'低い','低')[0:2] == ('ambiguous',None)
    assert resolve(candidates,'低い','低','ひくい')[0:2] == ('resolved','ひく')
    assert resolve(candidates,'低い','低','てい')[0:2] == ('unsupported',None)


def test_kuru_bare_stem_is_not_guessed():
    assert resolve({'来る':(lex('来る','くる','Kuru verb - special class'),)},'来る','来')[1] is None


def test_multiple_entries_same_reading_keep_all_bindings():
    status,reading,bindings=resolve({'橋':(lex('橋','はし','noun','1'),lex('橋','はし','noun','2'))},'橋','橋')
    assert (status,reading)==('resolved','はし')
    assert {b[0] for b in bindings}=={'1','2'}


def test_restrictions_and_sense_pos_are_applied_per_spelling_reading(tmp_path):
    path=tmp_path/'dictionary.gz'
    xml='''<JMdict><entry><ent_seq>1</ent_seq><k_ele><keb>見る</keb></k_ele><k_ele><keb>観る</keb></k_ele>
    <r_ele><reb>みる</reb></r_ele><r_ele><reb>かんる</reb><re_restr>観る</re_restr></r_ele>
    <sense><stagk>見る</stagk><pos>Ichidan verb</pos></sense>
    <sense><stagk>観る</stagk><stagr>みる</stagr><pos>Ichidan verb</pos></sense>
    <sense><stagk>観る</stagk><stagr>かんる</stagr><pos>noun</pos></sense></entry></JMdict>'''
    with gzip.open(path,'wt') as f:f.write(xml)
    candidates=dictionary_candidates(path,{'見る'})
    assert resolve(candidates,'見る','観')[0:2]==('resolved','み')
    assert all(not (l.spelling=='見る' and l.reading=='かんる') for l in candidates['見る'])


def test_lexical_honorific_has_own_entry():
    candidates={'手伝い':(), 'お手伝い':(lex('お手伝い','おてつだい','noun','honorific'),)}
    assert resolve(candidates,'手伝い','お手伝い')[0:2]==('resolved','おてつだい')
    assert resolve(candidates,'手伝い','お手伝い',entry_ref='unrelated')[1] is None


def test_special_godan_classes_are_not_regularized():
    for word,reading,pos,bad in [
        ('問う','とう',"Godan verb with 'u' ending (special class)",'問って'),
        ('下さる','くださる',"Godan verb - -aru special class",'下さります')]:
        assert bad not in inflections(lex(word,reading,pos))


def test_ii_and_special_ichidan_do_not_generate_false_forms():
    assert '良く' not in inflections(lex('良い','いい','adjective (keiyoushi)'))
    assert '呉れろ' not in inflections(lex('呉れる','くれる','Ichidan verb - kureru special class'))


def test_inflected_raw_lemma_binds_dictionary_not_standalone_surface(tmp_path):
    path=tmp_path/'dictionary.gz'
    with gzip.open(path,'wt') as f:
        f.write('<JMdict><entry><ent_seq>1</ent_seq><k_ele><keb>遠い</keb></k_ele><r_ele><reb>とおい</reb></r_ele><sense><pos>adjective (keiyoushi)</pos></sense></entry></JMdict>')
    candidates=dictionary_candidates(path,{'遠くて'})
    assert resolve(candidates,'遠くて','遠くて','とおくて')[0:2]==('resolved','とおくて')


def evidence_fixture(tmp_path, text='😀低と低を見る。'):
    path=tmp_path/'dictionary.gz'
    with gzip.open(path,'wt') as f:
        f.write('<JMdict><entry><ent_seq>1</ent_seq><k_ele><keb>低い</keb></k_ele><r_ele><reb>ひくい</reb></r_ele><sense><pos>adjective (keiyoushi)</pos></sense></entry></JMdict>')
    conn=sqlite3.connect(':memory:');conn.executescript(_SCHEMA)
    conn.execute('INSERT INTO sentence VALUES(?,?,?,?)',('s','s',text,'fixture'))
    conn.executemany('INSERT INTO sentence_token VALUES(?,?,?,?,?,?)',[
        ('s',0,'低い','低',None,None),('s',1,'低い','低',None,None)])
    return conn,path


def test_positional_contract_covers_repeated_tokens_and_utf16(tmp_path):
    conn,path=evidence_fixture(tmp_path)
    build_context_readings(conn,path)
    rows=conn.execute('SELECT pos,start_utf16,length_utf16,reading,status FROM sentence_token_readings ORDER BY pos').fetchall()
    assert rows==[(0,2,1,'ひく','resolved'),(1,4,1,'ひく','resolved')]
    for (bindings,) in conn.execute('SELECT bindings_json FROM sentence_token_readings'):
        assert json.loads(bindings)==[['1','低い','ひくい','ひく']]
    assert conn.execute('SELECT entry_ref,spelling,reading FROM context_dictionary_readings').fetchall()==[('1','低い','ひくい')]


def test_stale_positional_review_is_rejected(tmp_path):
    conn,path=evidence_fixture(tmp_path)
    review=tmp_path/'review.json'
    review.write_text(json.dumps({'schema_version':1,'occurrences':[dict(sent_id='s',pos=0,text='stale',lemma='低い',form='低',entry_ref='1',spelling='低い',lemma_reading='ひくい',reading='ひく')]}))
    with pytest.raises(ValueError,match='Stale'):
        build_context_readings(conn,path,review)


def test_conflicting_reviewed_evidence_is_rejected(tmp_path):
    conn,path=evidence_fixture(tmp_path,'低を見る。')
    conn.execute('DELETE FROM sentence_token WHERE pos=1')
    conn.execute('INSERT INTO verified_occurrence VALUES(?,?,?,?,?,?,?)',('s','1','低い','ひくい','低','ひっく','a'*64))
    review=tmp_path/'review.json'
    review.write_text(json.dumps({'schema_version':1,'occurrences':[dict(sent_id='s',pos=0,text='低を見る。',lemma='低い',form='低',entry_ref='1',spelling='低い',lemma_reading='ひくい',reading='ひく')]}))
    with pytest.raises(ValueError,match='Conflicting'):
        build_context_readings(conn,path,review)


def test_unaligned_token_prevents_later_repeated_token_rebinding(tmp_path):
    conn,path=evidence_fixture(tmp_path,'低を見る。')
    conn.execute("UPDATE sentence_token SET form='欠落' WHERE pos=0")
    build_context_readings(conn,path)
    assert conn.execute('SELECT status,reading FROM sentence_token_readings ORDER BY pos').fetchall()==[('unaligned',None),('unaligned',None)]


def test_adjective_appearance_exceptions_and_regular_kawaii():
    assert inflections(lex('高い','たかい','adjective (keiyoushi)')).get('高そう')=='たかそう'
    assert '高さそう' not in inflections(lex('高い','たかい','adjective (keiyoushi)'))
    assert '無そう' not in inflections(lex('無い','ない','adjective (keiyoushi)'))
    assert inflections(lex('無い','ない','adjective (keiyoushi)')).get('無さそう')=='なさそう'
    assert inflections(lex('良い','よい','adjective (keiyoushi)')).get('良さそう')=='よさそう'
    assert inflections(lex('可愛い','かわいい','adjective (keiyoushi)')).get('可愛く')=='かわいく'


def test_godan_emphatic_imperative_preserves_bound_stem():
    assert inflections(lex('入る','はいる',"Godan verb with 'ru' ending")).get('入れよ')=='はいれよ'
    assert '入れよ' not in inflections(lex('入る','いる',"Godan verb with 'ru' ending (irregular verb)"))


def test_a_real_lemma_excludes_unrelated_reverse_inflection_entries():
    candidates={'回':(lex('回','かい','noun','counter'),lex('回る','みる','Ichidan verb','verb'))}
    assert resolve(candidates,'回','回')[0:2]==('resolved','かい')
    assert resolve(candidates,'回','回')[2]==[('counter','回','かい','かい')]


def test_search_only_readings_are_retained_but_not_default_display():
    standard=lex('全然','ぜんぜん','adverb','1')
    search=Lexeme('1','全然','ぜんっぜん',('adverb',),True)
    candidates={'全然':(standard,search)}
    assert resolve(candidates,'全然','全然')[0:2]==('resolved','ぜんぜん')
    assert resolve(candidates,'全然','全然','ぜんっぜん')[0:2]==('resolved','ぜんっぜん')
    assert search in candidates['全然'], 'display policy cannot delete dictionary evidence'


def test_nominal_genitive_preserves_source_lemma_binding():
    candidates={'彼':(lex('彼','かれ','pronoun','he'),lex('彼','あれ','pronoun','that'))}
    assert resolve(candidates,'彼','彼の','かれ')[0:2]==('resolved','かれの')
    assert resolve({'時':(lex('時','じ','counter'),)},'時','時の','じ')[0:2]==('resolved','じの')


def test_yuku_special_class_does_not_manufacture_yutte():
    forms=inflections(lex('行く','ゆく','Godan verb - Iku/Yuku special class'))
    assert forms=={'行く':'ゆく'}
    assert inflections(lex('行く','いく','Godan verb - Iku/Yuku special class')).get('行って')=='いって'


def test_explicit_unresolved_binding_cannot_fall_back_to_dictionary(tmp_path):
    conn,path=evidence_fixture(tmp_path,'低を見る。')
    conn.execute('DELETE FROM sentence_token WHERE pos=1')
    review=tmp_path/'review.json'
    review.write_text(json.dumps({'schema_version':1,'occurrences':[dict(sent_id='s',pos=0,text='低を見る。',lemma='低い',form='低',decision='unresolved_binding')]}))
    build_context_readings(conn,path,review)
    assert conn.execute('SELECT status,reading,evidence_kind FROM sentence_token_readings').fetchone()==('unsupported',None,'reviewed_position')
