"""Build position-bound contextual readings; never infer from an isolated form.

Raw corpus annotations remain untouched. Dictionary restrictions and POS constrain
candidates; unresolved ambiguity is data, not permission to choose a first reading.
"""
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KANJI = re.compile(r"[\u3400-\u9fff\U00020000-\U0002ffff]")
KANA = re.compile(r"[\u3041-\u3096\u30fc]+")


def kana(text):
    return ''.join(chr(ord(c)-0x60) if '\u30a1' <= c <= '\u30f6' else c for c in text)


@dataclass(frozen=True)
class Lexeme:
    entry: str
    spelling: str
    reading: str
    pos: tuple[str, ...]
    search_only: bool = False


def dictionary_candidates(path, wanted):
    """Streaming parse: retain only lexical features needed by corpus tokens."""
    result = {}
    prefixes = {word[:i] for word in wanted for i in range(1,len(word)+1)}
    with gzip.open(path, 'rb') as stream:
        for _, entry in ET.iterparse(stream, events=('end',)):
            if entry.tag != 'entry':
                continue
            spellings = [k.findtext('keb') for k in entry.findall('k_ele')]
            if not any(word in wanted or word[:-1] in prefixes or word[:-2] in prefixes for word in spellings):
                entry.clear()
                continue
            ident = entry.findtext('ent_seq')
            inherited = ()
            senses = []
            for sense in entry.findall('sense'):
                explicit = tuple(p.text for p in sense.findall('pos') if p.text)
                if explicit:
                    inherited = explicit
                senses.append((set(x.text for x in sense.findall('stagk')),
                               set(x.text for x in sense.findall('stagr')), inherited))
            variants = []
            for reading in entry.findall('r_ele'):
                raw = reading.findtext('reb') or ''
                normalized = kana(raw)
                if not KANA.fullmatch(normalized) or reading.find('re_nokanji') is not None:
                    continue
                restricted = set(r.text for r in reading.findall('re_restr'))
                for spelling in spellings:
                    if restricted and spelling not in restricted:
                        continue
                    parts = set()
                    for stagk, stagr, pos in senses:
                        if (not stagk or spelling in stagk) and (not stagr or raw in stagr):
                            parts.update(pos)
                    if parts:
                        variants.append(Lexeme(ident, spelling, normalized, tuple(sorted(parts)),
                                               any(x.text == 'search-only kana form' for x in reading.findall('re_inf'))))
            # A token lemma can bind another spelling only inside this same entry.
            for spelling in set(spellings).intersection(wanted):
                result.setdefault(spelling, set()).update(variants)
            # Some authored source tokens use an inflected form as their raw
            # lemma. Bind it through supported dictionary morphology at build
            # time; never fabricate an entry or rewrite the source annotation.
            for variant in variants:
                for form in inflections(variant):
                    if form in wanted:
                        result.setdefault(form,set()).add(variant)
            entry.clear()
    return {key: tuple(sorted(values, key=lambda x: (x.entry,x.spelling,x.reading,x.pos)))
            for key, values in result.items()}


def inflections(lexeme):
    """Bounded modern forms, selected by dictionary POS, not written ending alone."""
    word, reading, pos = lexeme.spelling, lexeme.reading, lexeme.pos
    forms = {word: reading}
    def append(written, spoken, endings):
        if written:
            for ending in endings:
                forms[written+ending] = spoken+ending
    if 'adjective (keiyoushi)' in pos and word.endswith('い') and reading.endswith('い') and reading != 'いい' and not (reading.endswith('いい') and word.endswith(('良い','好い','いい'))):
        append(word[:-1], reading[:-1], ['', 'く', 'かった', 'くて', 'くない', 'くなかった', 'ければ', 'さ', 'すぎて'])
        # Appearance forms have irregular -sa insertion for よい/ない.
        if reading in ('よい','ない'):
            append(word[:-1],reading[:-1],['さそう'])
        elif not reading.endswith('ない'):
            append(word[:-1],reading[:-1],['そう'])
    if 'Ichidan verb' in pos and word.endswith('る') and reading.endswith('る'):
        append(word[:-1], reading[:-1], ['', 'て', 'た', 'ない', 'ないで', 'なかった', 'ます', 'ました', 'ません', 'ませんでした', 'れば', 'ろ', 'よ', 'よう', 'られる', 'られた', 'られない', 'させる', 'ましょう', 'ている', 'ていた', 'ています', 'ていました', 'そう', 'たら', 'たく', 'たい', 'たかった', 'られて', 'られている', 'られています'])
    if any(p.startswith('suru verb') for p in pos) and word.endswith('する') and reading.endswith('する'):
        append(word[:-2], reading[:-2], ['し', 'して', 'した', 'しない', 'しなかった', 'します', 'しました', 'しません', 'しませんでした', 'しましょう', 'している', 'していた', 'すれば', 'しろ', 'せよ', 'しよう', 'される', 'された'])
    if any('takes the aux. verb suru' in p for p in pos):
        append(word,reading,['する','し','した','して','しない','しなかった','します','しました','しません','している','していた'])
    ordinary_godan = {f"Godan verb with '{ending}' ending" for ending in ['u','ku','gu','su','tsu','nu','bu','mu','ru']}
    godan = bool(ordinary_godan.intersection(pos)) or any('Iku/Yuku' in p for p in pos)
    # The yuku alternative has irregular historical forms; do not manufacture ゆって.
    if any('Iku/Yuku' in p for p in pos) and reading.endswith('ゆく'):
        godan = False
    if godan and word and reading and word[-1] == reading[-1]:
        endings = {'う':('い','わ','え','お','って'), 'く':('き','か','け','こ','いて'),
                   'ぐ':('ぎ','が','げ','ご','いで'), 'す':('し','さ','せ','そ','して'),
                   'つ':('ち','た','て','と','って'), 'ぬ':('に','な','ね','の','んで'),
                   'ぶ':('び','ば','べ','ぼ','んで'), 'む':('み','ま','め','も','んで'),
                   'る':('り','ら','れ','ろ','って')}
        if word[-1] in endings:
            i,a,e,o,te = endings[word[-1]]
            if any('Iku/Yuku' in p for p in pos):
                te = 'って'
            ta = te[:-1]+('だ' if te.endswith('で') else 'た')
            suffixes = [i, te, ta, ta+'ら', a+'ない', a+'なかった', e, e+'よ', e+'ば', o+'う', i+'たい', i+'たく', i+'にくい', te+'いて', te+'て']
            suffixes += [i+x for x in ['ます','ました','ません','ませんでした','ましょう']]
            suffixes += [te+x for x in ['いる','いた','います','いました','いない','いなかった']]
            suffixes += [e+x for x in ['る','た','ない','なかった','ます','ました','て','ている']]
            suffixes += [a+x for x in ['れる','れた','れない','れなかった','れて','れている','れています','れている','せる','せた']]
            append(word[:-1], reading[:-1], suffixes)
            # Recognize only the observed お+ordinary-Godan continuative.
            # This establishes pronunciation, not honorific suitability in context.
            if ordinary_godan.intersection(pos):
                forms['お'+word[:-1]+i] = 'お'+reading[:-1]+i
    if any('noun' in p or p in ('pronoun','counter') for p in pos):
        append(word,reading,['の'])
    if any('keiyodoshi' in p for p in pos):
        append(word,reading,['な','に','で','だ','だった','ではない','じゃない'])
    # Kuru's written stem changes reading. Only complete, recognized forms are
    # supported here; a bare written stem requires positional reviewed evidence.
    if 'Kuru verb - special class' in pos and word.endswith('る') and reading == 'くる':
        base = word[:-1]
        for tail, spoken in {'た':'きた','て':'きて','ます':'きます','ました':'きました',
                             'ない':'こない','なかった':'こなかった','よう':'こよう',
                             'い':'こい','れば':'くれば'}.items():
            forms[base+tail] = spoken
    return forms


def resolve(lexicon, lemma, form, annotation=None, entry_ref=None):
    candidates = set()
    tagged = kana(annotation) if annotation else None
    direct_entries = {lex.entry for lex in lexicon.get(lemma, ()) if lex.spelling == lemma}
    for lex in lexicon.get(lemma, ()):
        if direct_entries and lex.entry not in direct_entries:
            continue
        if entry_ref is not None and lex.entry != entry_ref:
            continue
        # Search-only spellings remain lexical evidence, but are not default
        # standard-display candidates. An explicit source reading can select one.
        if lex.search_only and tagged is None:
            continue
        reading = inflections(lex).get(form)
        if reading is None or (tagged is not None and tagged not in (lex.reading,reading)):
            continue
        candidates.add((lex.entry,lex.spelling,lex.reading,reading))
    # Lexicalized honorifics need their own dictionary entry, not generic stripping.
    if not candidates and entry_ref is None and form.startswith(('お','ご')) and form[1:] == lemma:
        for lex in lexicon.get(form, ()):
            if lex.spelling == form and (tagged is None or tagged == lex.reading):
                candidates.add((lex.entry,lex.spelling,lex.reading,lex.reading))
    readings = {x[3] for x in candidates}
    if len(readings) == 1:
        return 'resolved', next(iter(readings)), sorted(candidates)
    if candidates:
        return 'ambiguous', None, sorted(candidates)
    return ('unsupported' if lemma in lexicon else 'unbound'), None, []


def build_context_readings(conn, dictionary_path, overrides_path=None):
    wanted = {x[0] for x in conn.execute('SELECT DISTINCT lemma FROM sentence_token')}
    wanted.update(x[0] for x in conn.execute('SELECT DISTINCT form FROM sentence_token'))
    lexicon = dictionary_candidates(dictionary_path, wanted)
    digest = hashlib.sha256()
    with open(dictionary_path,'rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            digest.update(chunk)
    names_path = Path(dictionary_path).parent / 'context_named_entities.json'
    if names_path.exists():
        names_bytes = names_path.read_bytes()
        names = json.loads(names_bytes)
        if names['schema_version'] != 1:
            raise ValueError('Unsupported named-entity dictionary extract')
        digest.update(names_bytes)
        for xml in names['entries_xml']:
            entry = ET.fromstring(xml)
            ident = 'jmnedict:'+entry.findtext('ent_seq')
            spellings = [x.text for x in entry.findall('k_ele/keb')]
            for item in entry.findall('r_ele'):
                reading = kana(item.findtext('reb') or '')
                restrictions = {x.text for x in item.findall('re_restr')}
                if not KANA.fullmatch(reading):
                    continue
                for spelling in spellings:
                    if spelling in wanted and (not restrictions or spelling in restrictions):
                        lexicon[spelling] = lexicon.get(spelling,())+(Lexeme(ident,spelling,reading,('proper name',)),)
    source_hash = digest.hexdigest()
    dictionary_bindings = {}
    for values in lexicon.values():
        for lexeme in values:
            key = (lexeme.entry, lexeme.spelling, lexeme.reading)
            # Kana normalization can merge normal/search-only reading variants.
            # A normal attestation wins regardless of set/dictionary iteration order.
            dictionary_bindings[key] = dictionary_bindings.get(key, True) and lexeme.search_only
    overrides = {}
    if overrides_path is not None and Path(overrides_path).exists():
        spec = json.loads(Path(overrides_path).read_text())
        if spec['schema_version'] != 1:
            raise ValueError('Unsupported contextual reading review version')
        for source in spec.get('review_sources',[]):
            payload = (Path(overrides_path).parent / source['file']).read_bytes()
            if hashlib.sha256(payload).hexdigest() != source['sha256']:
                raise ValueError('Contextual review source hash mismatch')
        for item in spec['occurrences']:
            key = item['sent_id'], item['pos']
            if key in overrides:
                raise ValueError('Duplicate contextual reading review position')
            overrides[key] = item
    seen = set()
    @lru_cache(maxsize=100000)
    def cached(lemma,form,annotation,entry):
        return resolve(lexicon,lemma,form,annotation,entry)
    rows = conn.execute('SELECT s.sent_id,s.text,t.pos,t.lemma,t.form,t.reading,t.entry_ref FROM sentence s JOIN sentence_token t USING(sent_id) ORDER BY s.sent_id,t.pos')
    last, cursor = None, 0
    output, counts = [], {}
    for sid,text,pos,lemma,form,annotation,entry in rows:
        if sid != last:
            last,cursor = sid,0
        start = text.find(form,cursor) if form else -1
        if start >= 0:
            cursor = start+len(form)
        else:
            cursor = len(text)+1
        if not KANJI.search(form):
            continue
        status,reading,bindings = cached(lemma,form,annotation,entry)
        kind = ('source_annotation' if annotation else 'dictionary') if status == 'resolved' else 'unresolved'
        provenance = source_hash
        item = overrides.get((sid,pos))
        if item is not None:
            seen.add((sid,pos))
            if (text,lemma,form) != (item['text'],item['lemma'],item['form']) or start < 0:
                raise ValueError(f'Stale contextual reading review: {sid}:{pos}')
            decision = item.get('decision','resolve')
            if decision not in ('resolve','unresolved_binding'):
                raise ValueError('Unsupported contextual review decision')
            if decision == 'unresolved_binding':
                status,reading,bindings = 'unsupported',None,[]
            else:
                binding = item['entry_ref'],item['spelling'],item['lemma_reading'],item['reading']
                if not any((l.entry,l.spelling,l.reading) == binding[:3] for l in lexicon.get(lemma, ())+lexicon.get(form, ())):
                    raise ValueError(f'Unbound contextual reading review: {sid}:{pos}')
                if not KANA.fullmatch(item['reading']):
                    raise ValueError('Reviewed context reading must be kana')
                status,reading,bindings = 'resolved',item['reading'],[binding]
            kind = 'reviewed_position'
            provenance = hashlib.sha256(json.dumps(item,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        # Already validated target occurrence evidence is position-safe only when
        # exactly one token and one text occurrence match its identity.
        verified = conn.execute('SELECT entry_ref,lemma_reading,reading,provenance_sha256 FROM verified_occurrence WHERE sent_id=? AND lemma=? AND form=?', (sid,lemma,form)).fetchall()
        if len(verified) == 1 and text.count(form) == 1 and conn.execute('SELECT count(*) FROM sentence_token WHERE sent_id=? AND lemma=? AND form=?',(sid,lemma,form)).fetchone()[0] == 1:
            ref,base,spoken,sha = verified[0]
            if item is not None and (item.get('entry_ref'),item.get('reading')) != (ref,spoken):
                raise ValueError(f'Conflicting positional/target reading evidence: {sid}:{pos}')
            if item is None and any((l.entry,l.spelling,l.reading) == (ref,lemma,base) for l in lexicon.get(lemma, ())):
                status,reading,bindings,provenance = 'resolved',spoken,[(ref,lemma,base,spoken)],sha
                kind = 'reviewed_target'
        if start < 0:
            status,reading,bindings = 'unaligned',None,[]
            kind = 'unresolved'
        offset = len(text[:start].encode('utf-16-le'))//2 if start >= 0 else None
        length = len(form.encode('utf-16-le'))//2
        encoded = json.dumps(bindings,ensure_ascii=False,separators=(',',':'))
        digest = hashlib.sha256(json.dumps([provenance,text,pos,lemma,form,annotation,entry,status,reading,encoded],ensure_ascii=False).encode()).hexdigest()
        output.append((sid,pos,offset,length,status,reading,encoded,digest,kind))
        counts[status] = counts.get(status,0)+1
        if len(output) >= 5000:
            conn.executemany('INSERT INTO token_reading_evidence VALUES(?,?,?,?,?,?,?,?,?)',output)
            output.clear()
    conn.executemany('INSERT INTO token_reading_evidence VALUES(?,?,?,?,?,?,?,?,?)',output)
    conn.executemany('INSERT INTO context_dictionary_reading VALUES(?,?,?,?,?)',
                     [(ref,spelling,reading,source_hash,int(search_only))
                      for (ref,spelling,reading),search_only in sorted(dictionary_bindings.items())])
    if set(overrides) != seen:
        raise ValueError('Contextual review references missing token positions')
    return counts
