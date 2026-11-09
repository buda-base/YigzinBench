"""Text normalization and per-page CER.

Copied unchanged from BDRC's reference scorer, `runs/compute_cer.py` in
https://huggingface.co/datasets/BDRC/tibetan-ocr-benchmark, so that scores here
match the numbers BDRC publishes. Do not change this logic without bumping
SCORER_VERSION in scorer/score.py and re-scoring every submission.

  * the hypothesis is normalized with botok (the ground truth is pre-normalized);
  * all whitespace is stripped and repeated tsheg (U+0F0B) folded to one;
  * placeholder characters (K O B I S) are removed on both sides;
  * CER = Levenshtein(hyp, ref) / len(ref), capped at 1.0 per page.
"""
import re

from botok.utils.corpus_normalization import normalize_spaces
from botok.utils.lenient_normalization import normalize_graphical
from botok.utils.unicode_normalization import normalize_unicode
from rapidfuzz.distance import Levenshtein

CATASTROPHIC_THRESHOLD = 0.5
PLACEHOLDERS = frozenset("KOBIS")
_MULTI_TSHEG_RE = re.compile("་{2,}")


def normalize_hypothesis(text: str) -> str:
    text = text.replace(" ", " ")
    text = normalize_spaces(text, tibetan_specific=False)
    text = normalize_unicode(text)
    text = normalize_graphical(text)
    return text.strip(" \n\r")


def prepare(text: str, is_hypothesis: bool = False) -> str:
    if is_hypothesis:
        text = normalize_hypothesis(text)
    text = "".join(text.split())
    text = _MULTI_TSHEG_RE.sub("་", text)
    return "".join(c for c in text if c not in PLACEHOLDERS)


def cer(hyp_raw: str, ref_prepared: str) -> float:
    hyp = prepare(hyp_raw, is_hypothesis=True)
    if not ref_prepared:
        return 0.0 if not hyp else 1.0
    return min(Levenshtein.distance(hyp, ref_prepared) / len(ref_prepared), 1.0)
