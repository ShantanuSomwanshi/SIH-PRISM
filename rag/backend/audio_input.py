"""
Voice input: turn a spoken query into English text with Groq's Whisper.

One call to Groq's audio *translations* endpoint takes speech in any
language Whisper supports - English, Hindi, Marathi, Tamil and so on - and
returns English text. That text is then searched exactly like a typed
query, so nothing downstream needs to know the query was spoken.

This deliberately does not use IndicLID or IndicTrans2 (query_language.py):
those are not yet verified at runtime, and Whisper already does detection
and translation in one step.

Uses the official `groq` SDK rather than langchain-groq, because LangChain
does not expose the audio endpoints. The client is created on first use,
so importing this module costs nothing when voice input is switched off.
"""

import logging
import re
from typing import Optional

from backend.config import (
    AUDIO_MAX_NO_SPEECH_PROB,
    AUDIO_MIN_AVG_LOGPROB,
    AUDIO_MODEL,
)

logger = logging.getLogger("prism")

# What a browser recording (webm/ogg/mp4) or a saved clip is likely to be.
# All of these are formats Groq's Whisper accepts.
SUPPORTED_AUDIO_SUFFIXES = {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".flac"}

# One transcription should take seconds. Without a timeout a stalled
# connection would hold the request open indefinitely.
_REQUEST_TIMEOUT_SECONDS = 60.0

# What Whisper says when it hears silence, a muted microphone or room
# noise. It was trained on subtitled video, so an empty clip comes back as
# the stock phrases that end videos - often WITH a low no_speech_prob, so
# the score check alone does not catch it. None of these is ever a
# procurement query, so an exact match is always treated as "not heard".
SILENCE_PHRASES = {
    "thank you", "thank you very much", "thanks", "thanks for watching",
    "thank you for watching", "thank you so much for watching",
    "please subscribe", "like and subscribe", "you", "bye", "bye bye",
    "okay", "ok", "so", "uh", "um", "hmm", "music",
    "subtitles by the amara org community",
}

_client = None


def _get_client():
    """The Groq client, created once. Reads GROQ_API_KEY from the environment."""
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=1)
    return _client


def _as_dict(response) -> dict:
    """
    The SDK returns a pydantic model whose typed fields cover only `text`;
    verbose_json adds `segments` as extra fields. model_dump() includes
    both, whichever SDK version is installed.
    """
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return {"text": getattr(response, "text", "")}


def transcribe_to_english(audio_bytes: bytes, filename: str) -> dict:
    """
    Send one recording to Whisper and get English text back.

    Returns:
        text            the English text, stripped
        avg_logprob     mean of the segments' avg_logprob (None if no segments)
        no_speech_prob  highest no_speech_prob across segments (None if none)
        segments        how many segments Whisper returned

    Raises on any Groq failure (network, auth, rate limit). The caller turns
    that into a friendly response; nothing here is shown to the user.
    """
    if "turbo" in AUDIO_MODEL.lower():
        # Turbo only transcribes. Called for translation it fails, or on
        # some versions quietly returns non-English text.
        raise RuntimeError(
            f"AUDIO_MODEL={AUDIO_MODEL!r} does not support translation; "
            "use whisper-large-v3."
        )

    response = _get_client().audio.translations.create(
        file=(filename, audio_bytes),
        model=AUDIO_MODEL,
        response_format="verbose_json",
        temperature=0.0,
    )
    data = _as_dict(response)

    segments = data.get("segments") or []
    logprobs = [float(s["avg_logprob"]) for s in segments
                if isinstance(s, dict) and s.get("avg_logprob") is not None]
    no_speech = [float(s["no_speech_prob"]) for s in segments
                 if isinstance(s, dict) and s.get("no_speech_prob") is not None]

    return {
        "text": (data.get("text") or "").strip(),
        "avg_logprob": sum(logprobs) / len(logprobs) if logprobs else None,
        "no_speech_prob": max(no_speech) if no_speech else None,
        "segments": len(segments),
    }


def rejection_reason(result: dict) -> Optional[str]:
    """
    Why this transcription should NOT be searched, or None if it is usable.

    Fail-safe, like the rest of PRISM: a mis-heard query produces a
    confident-looking recommendation for the wrong product, which is worse
    than asking the user to say it again. Missing quality scores count as a
    failure rather than a pass - if we cannot tell how well Whisper heard,
    we do not assume it heard well.
    """
    if not result.get("text"):
        return "no speech was recognised"

    normalised = " ".join(re.sub(r"[^a-z0-9]+", " ", result["text"].lower()).split())
    if normalised in SILENCE_PHRASES:
        return f"heard only {result['text']!r}, Whisper's usual output for silence"

    avg_logprob = result.get("avg_logprob")
    no_speech_prob = result.get("no_speech_prob")
    if avg_logprob is None or no_speech_prob is None:
        return "Whisper returned no quality scores"
    if no_speech_prob > AUDIO_MAX_NO_SPEECH_PROB:
        return (f"no_speech_prob {no_speech_prob:.2f} is above "
                f"{AUDIO_MAX_NO_SPEECH_PROB}")
    if avg_logprob < AUDIO_MIN_AVG_LOGPROB:
        return (f"avg_logprob {avg_logprob:.2f} is below "
                f"{AUDIO_MIN_AVG_LOGPROB}")
    return None
