"""Indic language detection and translation for recommendation queries."""

import logging
import math
import importlib.util
import os
import sys
from pathlib import Path

from backend.config import (
    INDICLID_CODE_DIR,
    INDICLID_MODEL_ROOT,
    QUERY_LANGUAGE_MIN_CONFIDENCE,
)

logger = logging.getLogger("prism")

ENGLISH = "eng_Latn"

_lid = None
_indic_to_en = None
_en_to_indic = None


def _load_indiclid():
    """Load IndicLID and its three release models from configured paths."""
    code_dir = Path(INDICLID_CODE_DIR)
    model_root = Path(INDICLID_MODEL_ROOT)
    source_file = code_dir / "IndicLID.py"
    required = (
        model_root / "models" / "indiclid-ftn" / "model_baseline_roman.bin",
        model_root / "models" / "indiclid-ftr" / "model_baseline_roman.bin",
        model_root / "models" / "indiclid-bert" / "basline_nn_simple.pt",
    )
    missing = [
        str(path) for path in (source_file, *required) if not path.is_file()
    ]
    if missing:
        raise RuntimeError(
            "IndicLID is not installed. Place IndicLID.py in "
            f"{code_dir} and the three release model files under "
            f"{model_root / 'models'}; missing: {', '.join(missing)}"
        )

    spec = importlib.util.spec_from_file_location(
        "prism_indiclid_source", source_file
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load IndicLID source from {source_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module

    # Upstream IndicLID resolves models/.. relative to the process cwd.
    previous_cwd = os.getcwd()
    try:
        os.chdir(model_root)
        spec.loader.exec_module(module)
        return module.IndicLID()
    finally:
        os.chdir(previous_cwd)


def _load_translation_model(checkpoint: str):
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    model = AutoModelForSeq2SeqLM.from_pretrained(
        checkpoint, trust_remote_code=True
    )
    model.eval()
    return {
        "tokenizer": AutoTokenizer.from_pretrained(
            checkpoint, trust_remote_code=True
        ),
        "model": model,
    }


def load_models() -> None:
    """Load IndicLID and both distilled IndicTrans2 models once."""
    global _lid, _indic_to_en, _en_to_indic

    if _lid is not None:
        return

    _lid = _load_indiclid()
    _indic_to_en = _load_translation_model(
        "ai4bharat/indictrans2-indic-en-dist-200M"
    )
    _en_to_indic = _load_translation_model(
        "ai4bharat/indictrans2-en-indic-dist-200M"
    )


def _detect_language_confidence(text: str) -> tuple[str, float]:
    """Adapt IndicLID's actual batch result to a language/confidence pair."""
    # IndicLID.predict() currently discards its own return value. Its public
    # batch interface returns: (text, language_code, score, model_name).
    text_value, language, score, model_name = _lid.batch_predict([text], 1)[0]
    if text_value != text:
        logger.debug("IndicLID returned normalized input text")

    confidence = float(score)
    if model_name == "IndicLID-BERT":
        # The upstream BERT branch returns its winning raw logit, not a
        # calibrated probability. Sigmoid is only a bounded confidence
        # approximation accepted here for conservative thresholding.
        confidence = 1.0 / (1.0 + math.exp(-confidence))
    return language, confidence


def detect_language(text: str) -> str:
    """Return an IndicTrans2 code, or English when detection is uncertain."""
    language, confidence = _detect_language_confidence(text)
    if (
        language in {"", "other"}
        or confidence < QUERY_LANGUAGE_MIN_CONFIDENCE
    ):
        # Fail safe: uncertain input uses the existing English pipeline.
        return ENGLISH
    return language


def _translate(text: str, source_lang: str, target_lang: str, bundle) -> str:
    import torch
    from IndicTransToolkit.processor import IndicProcessor

    processor = IndicProcessor(inference=True)
    batch = processor.preprocess_batch(
        [text], src_lang=source_lang, tgt_lang=target_lang, visualize=False
    )
    encoded = bundle["tokenizer"](
        batch, padding="longest", truncation=True,
        max_length=256, return_tensors="pt",
    )
    with torch.inference_mode():
        output = bundle["model"].generate(
            **encoded, num_beams=5, num_return_sequences=1,
            max_length=256,
        )
    decoded = bundle["tokenizer"].batch_decode(
        output, skip_special_tokens=True,
        clean_up_tokenization_spaces=True,
    )
    return processor.postprocess_batch(decoded, lang=target_lang)[0]


def translate_to_en(text: str, source_lang: str) -> str:
    if source_lang == ENGLISH:
        return text
    return _translate(text, source_lang, ENGLISH, _indic_to_en)


def translate_from_en(text: str, target_lang: str) -> str:
    if not text or target_lang == ENGLISH:
        return text
    return _translate(text, ENGLISH, target_lang, _en_to_indic)
