"""Substantive-English assessment for prospective task scoping.

Purpose: decide whether a task's *natural-language content* is English, robustly enough to
scope a confirmatory study to English-only tasks. This deliberately does NOT trust
short-text language detection: `langdetect` mislabels short prompts, code-heavy prompts, and
mathematically symbolic prompts routinely (it labelled an all-English MT-Bench prompt as
Spanish, and labelled short Arena-Hard code snippets as Somali, Catalan, Norwegian and
Croatian). Its label is recorded as one signal among several and never used alone.

Two rules shape the design:

  1. **A code-heavy or symbol-heavy task is not non-English.** A prompt that is mostly a C
     program, a SQL query, or a block of LaTeX has little natural-language prose to classify.
     Such a task is treated as English-compatible provided it carries no positive evidence of
     another language. Excluding it for containing code would be excluding on a property we
     explicitly want represented.

  2. **Positive evidence of another language is what excludes.** Non-Latin script beyond
     incidental use, Vietnamese diacritics, or another language's function words outnumbering
     English's in the prose — those exclude. Absence of English prose does not.

Signals computed per task:

  * **Script profile.** Letters bucketed by Unicode range: Latin, CJK, Cyrillic, Hangul,
    Kana, Arabic, Hebrew, Devanagari, Thai, Greek. Computed on the FULL text, so Chinese or
    Russian comments inside an otherwise-English code block are still caught.
  * **Code-stripped prose.** Fenced/inline code, LaTeX, URLs, HTML tags, tables, identifiers,
    and long numeric/operator runs are removed before any lexical test, so `for (int i = 0;`
    cannot masquerade as prose in an unknown language.
  * **Function-word counts** for English and eleven other Latin-script languages, on the
    prose only.
  * **Vietnamese diacritic count** (U+1EA0–U+1EF9 and friends) — an unusually reliable marker.
  * **langdetect label** — recorded, weighted as advisory only.

The verdict is one of `english`, `english_low_prose` (rule 1 above), `non_english`, or
`needs_review`. Everything landing in `needs_review` is read by a human and recorded in an
explicit decision list; the automated verdict is never the final word on an ambiguous case.
Thresholds are stated as named constants so the rule is auditable rather than implicit.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---- thresholds (named so the decision rule is auditable) ----
NON_LATIN_RATIO_DECISIVE = 0.10   # >=10% of letters in a non-Latin script
NON_LATIN_COUNT_DECISIVE = 20     # ...and at least this many such letters
# Above this the script evidence is overwhelming; between DECISIVE and this it is a large
# but possibly-embedded block (a single foreign string literal, a quoted passage), so those
# go to human review instead of being auto-excluded.
NON_LATIN_RATIO_OVERWHELMING = 0.20
VIETNAMESE_MARKER_DECISIVE = 5
MIN_PROSE_WORDS_FOR_LEXICAL = 10  # below this, lexical tests are unreliable
ENGLISH_STOPWORD_RATIO_MIN = 0.08
FOREIGN_STOPWORD_MIN = 3
# A Latin-script lexical suspicion is only allowed to EXCLUDE when the language's own
# diacritics corroborate it. Without this, code tokens masquerade as function words: a C++
# snippet reading "how to make this code more memory efficient" scores 19 Czech "function
# words" (i, a, v, se, to, z, do, po are all common identifiers) against 11 English ones and
# would be wrongly excluded. Real prose in an accented language carries its accents.
LANG_DIACRITIC_MIN = 3

_SCRIPT_RANGES = {
    "cjk": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF)],
    "kana": [(0x3040, 0x30FF), (0x31F0, 0x31FF)],
    "hangul": [(0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F)],
    "cyrillic": [(0x0400, 0x04FF), (0x0500, 0x052F)],
    "arabic": [(0x0600, 0x06FF), (0x0750, 0x077F)],
    "hebrew": [(0x0590, 0x05FF)],
    "devanagari": [(0x0900, 0x097F)],
    "thai": [(0x0E00, 0x0E7F)],
    "greek": [(0x0370, 0x03FF)],
}

# U+1EA0-U+1EF9 is Vietnamese-specific Latin Extended Additional; the loose chars are the
# other distinctively Vietnamese letters.
_VIET_LOOSE = set("ăâđêôơưĂÂĐÊÔƠƯ")

_STOPWORDS: Dict[str, set] = {
    "english": {"the", "of", "and", "to", "in", "is", "that", "for", "with", "as", "are",
                "be", "this", "from", "on", "you", "it", "your", "have", "or", "which",
                "please", "write", "how", "what", "can", "a", "an", "if", "by", "at",
                "not", "but", "all", "will", "would", "should", "there", "they", "we"},
    "spanish": {"el", "la", "los", "las", "de", "del", "que", "y", "en", "un", "una", "es",
                "por", "con", "para", "se", "su", "al", "lo", "como", "más", "pero", "sus",
                "le", "ya", "o", "porque", "muy", "sin", "sobre", "también", "hasta"},
    "french": {"le", "la", "les", "de", "des", "du", "et", "est", "un", "une", "dans",
               "pour", "que", "qui", "sur", "pas", "vous", "au", "aux", "ce", "il", "ne",
               "se", "plus", "par", "avec", "tout", "nous", "comme", "mais", "être"},
    "german": {"der", "die", "das", "und", "ist", "ein", "eine", "nicht", "mit", "für",
               "von", "zu", "auf", "sich", "des", "dem", "den", "im", "aus", "auch",
               "es", "an", "werden", "oder", "wird", "sie", "einen", "als", "wie"},
    "portuguese": {"o", "a", "os", "as", "de", "do", "da", "que", "e", "em", "um", "uma",
                   "é", "por", "com", "para", "se", "não", "mais", "como", "mas", "ao",
                   "dos", "das", "no", "na", "ou", "você", "são"},
    "italian": {"il", "lo", "la", "i", "gli", "le", "di", "che", "e", "in", "un", "una",
                "è", "per", "con", "non", "sono", "come", "più", "da", "del", "della",
                "si", "al", "ma", "anche", "se", "questo"},
    "dutch": {"de", "het", "een", "en", "van", "is", "in", "dat", "op", "te", "die",
              "niet", "met", "voor", "aan", "er", "om", "ook", "als", "maar", "worden"},
    "catalan": {"el", "la", "els", "les", "de", "que", "i", "en", "un", "una", "és",
                "per", "amb", "no", "més", "com", "del", "dels", "però", "això", "són"},
    "polish": {"i", "w", "z", "na", "do", "nie", "że", "się", "jest", "to", "o", "a",
               "dla", "jak", "od", "po", "przez", "być", "który", "ale"},
    "czech": {"a", "v", "se", "na", "je", "že", "s", "z", "do", "to", "pro", "ale",
              "jako", "být", "který", "od", "po", "nebo", "tak"},
    "indonesian": {"dan", "yang", "di", "dengan", "untuk", "dari", "ini", "itu", "pada",
                   "adalah", "tidak", "dalam", "akan", "atau", "ke", "saya", "bisa"},
    "romanian": {"și", "de", "la", "în", "cu", "pe", "un", "o", "este", "care", "pentru",
                 "nu", "din", "se", "ca", "sunt", "mai", "sau"},
}


_LANG_DIACRITICS: Dict[str, set] = {
    "spanish": set("áéíóúñü¡¿ÁÉÍÓÚÑ"),
    "french": set("àâçéèêëîïôùûüÿœÀÂÇÉÈÊËÎÏÔÙÛÜŒ"),
    "german": set("äöüßÄÖÜ"),
    "portuguese": set("ãáàâçéêíóôõúÃÁÀÂÇÉÊÍÓÔÕÚ"),
    "italian": set("àèéìíîòóùÀÈÉÌÍÎÒÓÙ"),
    "polish": set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"),
    "czech": set("áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ"),
    "dutch": set("ëïöüéÉ"),
    "catalan": set("àèéíïòóúüçÀÈÉÍÏÒÓÚÜÇ"),
    "romanian": set("ăâîșțĂÂÎȘȚ"),
    "indonesian": set(),   # no distinctive diacritics; must go to review
}


def _script_of(ch: str) -> Optional[str]:
    cp = ord(ch)
    for name, ranges in _SCRIPT_RANGES.items():
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return name
    if ch.isalpha():
        return "latin" if cp < 0x0250 or 0x1E00 <= cp <= 0x1EFF else "other"
    return None


def strip_code_and_notation(text: str) -> str:
    """Remove the things that are not natural-language prose, so lexical tests see prose."""
    t = text
    t = re.sub(r"```.*?```", " ", t, flags=re.S)          # fenced code
    t = re.sub(r"~~~.*?~~~", " ", t, flags=re.S)
    t = re.sub(r"`[^`]*`", " ", t)                          # inline code
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)           # urls
    t = re.sub(r"<[^>\n]{1,200}>", " ", t)                  # html/xml tags
    t = re.sub(r"\$\$.*?\$\$|\$[^$\n]{1,200}\$", " ", t, flags=re.S)   # latex math
    t = re.sub(r"\\[a-zA-Z]+\{[^}]*\}|\\[a-zA-Z]+", " ", t)            # latex commands
    t = re.sub(r"\b\w+_\w[\w_]*\b", " ", t)                 # snake_case identifiers
    t = re.sub(r"\b[a-z]+[A-Z]\w*\b", " ", t)               # camelCase identifiers
    t = re.sub(r"\b\w+\.\w+(?:\.\w+)*\s*\(", " ", t)        # a.b.c( call chains
    t = re.sub(r"[|]{1,2}[-: ]*[|]", " ", t)                # markdown table rules
    t = re.sub(r"[0-9]+(?:[.,][0-9]+)*", " ", t)            # numbers
    t = re.sub(r"[{}\[\]()<>=+\-*/^%#@~_\\|;]+", " ", t)    # operators/punctuation runs
    t = re.sub(r"\s+", " ", t)
    return t.strip()


@dataclass
class Assessment:
    verdict: str                     # english | english_low_prose | non_english | needs_review
    reason: str
    n_letters: int = 0
    script_counts: Dict[str, int] = field(default_factory=dict)
    non_latin_ratio: float = 0.0
    vietnamese_markers: int = 0
    prose_words: int = 0
    english_hits: int = 0
    english_ratio: float = 0.0
    best_foreign: Optional[str] = None
    best_foreign_hits: int = 0
    best_foreign_diacritics: int = 0
    langdetect_label: Optional[str] = None

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["script_counts"] = {k: v for k, v in self.script_counts.items() if v}
        return d


def assess(text: str, langdetect_label: Optional[str] = None) -> Assessment:
    # --- script profile on the full text ---
    counts: Dict[str, int] = {}
    viet = 0
    for ch in text:
        s = _script_of(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
        cp = ord(ch)
        if 0x1EA0 <= cp <= 0x1EF9 or ch in _VIET_LOOSE:
            viet += 1
    n_letters = sum(counts.values())
    # "other" (a letter in no enumerated range -- Armenian, Georgian, Ethiopic, Tamil, ...)
    # counts as non-Latin. Excluding it let an Armenian prompt through as "low prose, no
    # non-English evidence"; an unenumerated script must raise the flag, not lower it.
    n_non_latin = sum(v for k, v in counts.items() if k != "latin")
    non_latin_ratio = (n_non_latin / n_letters) if n_letters else 0.0

    # --- prose-only lexical profile ---
    prose = strip_code_and_notation(text)
    words = [w.strip(".,;:!?\"'()").lower() for w in prose.split()]
    words = [w for w in words if w and any(c.isalpha() for c in w)]
    n_words = len(words)
    wordset = words

    def hits(lang: str) -> int:
        sw = _STOPWORDS[lang]
        return sum(1 for w in wordset if w in sw)

    en_hits = hits("english")
    en_ratio = (en_hits / n_words) if n_words else 0.0
    foreign_scores = {l: hits(l) for l in _STOPWORDS if l != "english"}
    best_foreign = max(foreign_scores, key=lambda l: foreign_scores[l]) if foreign_scores else None
    best_hits = foreign_scores.get(best_foreign, 0) if best_foreign else 0

    lang_diac = sum(1 for ch in text if ch in _LANG_DIACRITICS.get(best_foreign or "", set()))

    base = dict(n_letters=n_letters, script_counts=counts, non_latin_ratio=round(non_latin_ratio, 4),
                vietnamese_markers=viet, prose_words=n_words, english_hits=en_hits,
                english_ratio=round(en_ratio, 4), best_foreign=best_foreign,
                best_foreign_hits=best_hits, langdetect_label=langdetect_label,
                best_foreign_diacritics=lang_diac)

    # --- rule 1: non-Latin script ---
    if non_latin_ratio >= NON_LATIN_RATIO_DECISIVE and n_non_latin >= NON_LATIN_COUNT_DECISIVE:
        dom = max((k for k in counts if k != "latin"),
                  key=lambda k: counts[k], default="non_latin")
        if non_latin_ratio >= NON_LATIN_RATIO_OVERWHELMING:
            return Assessment("non_english",
                              f"{dom} script is {non_latin_ratio:.0%} of letters "
                              f"({n_non_latin} chars)", **base)
        return Assessment("needs_review",
                          f"{dom} script is {non_latin_ratio:.0%} of letters ({n_non_latin} "
                          f"chars) -- substantial but possibly an embedded block; read it",
                          **base)

    # --- rule 2: Vietnamese diacritics ---
    if viet >= VIETNAMESE_MARKER_DECISIVE:
        return Assessment("non_english",
                          f"{viet} Vietnamese-specific diacritics", **base)

    # --- rule 3: enough prose for a lexical decision ---
    if n_words >= MIN_PROSE_WORDS_FOR_LEXICAL:
        if en_ratio >= ENGLISH_STOPWORD_RATIO_MIN and en_hits > best_hits:
            return Assessment("english",
                              f"English function words {en_hits}/{n_words} "
                              f"({en_ratio:.0%}) exceed best other ({best_foreign}={best_hits})",
                              **base)
        if best_hits > en_hits and best_hits >= FOREIGN_STOPWORD_MIN:
            # Corroboration required: without the language's own diacritics this is very
            # often code tokens colliding with a function-word list, not foreign prose.
            if lang_diac >= LANG_DIACRITIC_MIN:
                return Assessment("non_english",
                                  f"{best_foreign} function words {best_hits} exceed English "
                                  f"{en_hits}, corroborated by {lang_diac} {best_foreign} "
                                  f"diacritics", **base)
            return Assessment("needs_review",
                              f"{best_foreign} function words {best_hits} exceed English "
                              f"{en_hits} but only {lang_diac} {best_foreign} diacritics "
                              f"corroborate -- likely code tokens; read it", **base)
        return Assessment("needs_review",
                          f"prose present ({n_words} words) but neither language dominates "
                          f"(en={en_hits}, {best_foreign}={best_hits})", **base)

    # --- rule 4: little or no prose (code/math-heavy or very short) ---
    if n_non_latin == 0 and viet == 0 and best_hits == 0:
        return Assessment("english_low_prose",
                          f"only {n_words} prose words after stripping code/notation; "
                          f"no non-English script or lexical evidence", **base)
    return Assessment("needs_review",
                      f"little prose ({n_words} words) with some non-English signal "
                      f"(non_latin={n_non_latin}, viet={viet}, {best_foreign}={best_hits})",
                      **base)
