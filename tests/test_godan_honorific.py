"""Observed honorific continuatives stay dictionary-bound; not free prefix generation."""
from tangobon.context_readings import Lexeme, inflections, resolve
import pytest


def lex(word, reading, pos, entry='verb'):
    return Lexeme(entry, word, reading, (pos,))


@pytest.mark.parametrize('word,reading,pos,form,spoken', [
    ('会う', 'あう', "Godan verb with 'u' ending", 'お会い', 'おあい'),
    ('待つ', 'まつ', "Godan verb with 'tsu' ending", 'お待ち', 'おまち'),
    ('持つ', 'もつ', "Godan verb with 'tsu' ending", 'お持ち', 'おもち'),
    ('手伝う', 'てつだう', "Godan verb with 'u' ending", 'お手伝い', 'おてつだい'),
])
def test_ordinary_godan_honorific_continuative(word, reading, pos, form, spoken):
    item = lex(word, reading, pos)
    assert resolve({word: (item,)}, word, form) == ('resolved', spoken, [('verb', word, reading, spoken)])
    assert resolve({word: (item,)}, word, form, 'wrong')[1] is None
    assert resolve({word: (item,)}, word, form, entry_ref='other')[1] is None


def test_honorific_rule_keeps_ambiguity_and_lexical_entries():
    word = '会う'
    pool = {word: (lex(word, 'あう', "Godan verb with 'u' ending", 'a'),
                   lex(word, 'おう', "Godan verb with 'u' ending", 'b'))}
    assert resolve(pool, word, 'お会い')[:2] == ('ambiguous', None)
    assert resolve(pool, word, 'お会い', 'あう')[:2] == ('resolved', 'おあい')
    lexical = {'お手伝い': (lex('お手伝い', 'おてつだい', 'noun', '1612810'),)}
    assert resolve(lexical, 'お手伝い', 'お手伝い')[2] == [('1612810', 'お手伝い', 'おてつだい', 'おてつだい')]


def test_honorific_rule_does_not_expand_other_classes_or_prefixes():
    for item, form in [
        (lex('来る', 'くる', 'Kuru verb - special class'), 'お来'),
        (lex('問う', 'とう', "Godan verb with 'u' ending (special class)"), 'お問い'),
        (lex('下さる', 'くださる', 'Godan verb - -aru special class'), 'お下さり'),
        (lex('見る', 'みる', 'Ichidan verb'), 'お見'),
        (lex('行く', 'いく', 'Godan verb - Iku/Yuku special class'), 'お行き'),
        (lex('茶', 'ちゃ', 'noun'), 'お茶'),
        (lex('会う', 'あう', "Godan verb with 'u' ending"), 'ご会い'),
        (lex('会う', 'あう', "Godan verb with 'u' ending"), 'お会って'),
    ]:
        assert form not in inflections(item)
