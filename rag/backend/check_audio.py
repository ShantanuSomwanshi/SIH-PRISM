"""
Check the voice input endpoint end to end against a running server.

Start the API first (uvicorn backend.main:app), then from the "rag" folder:

    python -m backend.check_audio                      # silent + noise clips only
    python -m backend.check_audio english.m4a hindi.m4a

Your own clips can be anything you recorded - Windows Voice Recorder saves
.m4a, which is accepted. A silent clip and a noise-only clip are generated
automatically every run (in a temporary folder, deleted afterwards); both
must come back as "please repeat", never as a recommendation.

With AUDIO_INPUT_ENABLED=false every clip should report 503 - that is the
check that the switch works.
"""

import argparse
import math
import os
import random
import struct
import sys
import tempfile
import wave

import requests

from backend.config import API_KEY

SAMPLE_RATE = 16000


def _write_wav(path: str, samples) -> None:
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def make_test_clips(folder: str) -> list:
    """A 3 s silent clip and a 3 s clip of hiss plus a low hum - no speech."""
    silent = os.path.join(folder, "silence.wav")
    noise = os.path.join(folder, "noise.wav")
    n = SAMPLE_RATE * 3
    _write_wav(silent, [0] * n)
    rng = random.Random(7)
    _write_wav(noise, [
        int(max(-32767, min(32767,
            rng.gauss(0, 2500) + 1500 * math.sin(2 * math.pi * 50 * i / SAMPLE_RATE))))
        for i in range(n)
    ])
    return [(silent, True), (noise, True)]


def check(url: str, path: str, expect_rejection: bool) -> bool:
    name = os.path.basename(path)
    print("=" * 64)
    print(name)
    print("-" * 64)
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    with open(path, "rb") as handle:
        try:
            res = requests.post(f"{url}/api/recommend/audio", headers=headers,
                                files={"file": (name, handle)}, timeout=180)
        except requests.RequestException as exc:
            print(f"  could not reach the server: {exc}")
            return False

    print(f"  HTTP status      {res.status_code}")
    try:
        body = res.json()
    except ValueError:
        print(f"  (not JSON) {res.text[:300]}")
        return False

    if res.status_code != 200:
        print(f"  detail           {body.get('detail')}")
        return res.status_code == 503 and "disabled" in str(body.get("detail", ""))

    quality = body.get("audio_quality") or {}
    print(f"  heard (English)  {body.get('transcript')!r}")
    print(f"  avg_logprob      {quality.get('avg_logprob')}")
    print(f"  no_speech_prob   {quality.get('no_speech_prob')}")
    print(f"  clarification    {body.get('clarification_needed')}")
    if body.get("message"):
        print(f"  message          {body.get('message')}")
    print(f"  primary standard {body.get('primary_standard')}")
    if body.get("primary_standard"):
        print(f"  title            {body.get('title')}")
        print(f"  confidence       {body.get('confidence')}")

    if expect_rejection:
        ok = body.get("clarification_needed") and not body.get("transcript") \
            and not body.get("primary_standard")
        print(f"  EXPECTED a 'please repeat' reply -> {'PASS' if ok else 'FAIL'}")
        return bool(ok)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Check POST /api/recommend/audio.")
    parser.add_argument("clips", nargs="*", help="your own recordings to send")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    try:
        health = requests.get(args.url + "/", timeout=10).json()
        print(f"Server is up: {health.get('chunks')} chunks indexed.\n")
    except Exception as exc:
        print(f"Server not reachable at {args.url} ({exc}). "
              "Start it with: uvicorn backend.main:app")
        return 1

    missing = [c for c in args.clips if not os.path.isfile(c)]
    if missing:
        print("Not found: " + ", ".join(missing))
        return 1

    results = []
    with tempfile.TemporaryDirectory() as folder:
        for path, expect_rejection in [(c, False) for c in args.clips] + make_test_clips(folder):
            results.append(check(args.url, path, expect_rejection))

    print("=" * 64)
    print(f"{sum(results)}/{len(results)} checks as expected")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
