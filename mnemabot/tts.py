"""Voiceover via Kokoro-82M (Apache-2.0, runs on CPU). Falls back to silence when unavailable.

synth(texts) -> list of (wav_path | None, duration_seconds)
"""
from __future__ import annotations

import os
import wave
from pathlib import Path

SR = 24000
VOICE = os.environ.get("MNEMA_VOICE", "af_heart")
SPEED = float(os.environ.get("MNEMA_VOICE_SPEED", "1.0"))

_pipe = None


def _pipeline():
    global _pipe
    if _pipe is None:
        from kokoro import KPipeline  # noqa: WPS433
        _pipe = KPipeline(lang_code="a")
    return _pipe


def available() -> bool:
    if os.environ.get("MNEMA_NO_TTS"):
        return False
    try:
        _pipeline()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[tts] unavailable: {e}")
        return False


def _estimate(text: str) -> float:
    return max(1.2, len(text.split()) / 2.7 + 0.25)


def synth(texts: list[str], workdir: Path) -> list[tuple[Path | None, float]]:
    workdir.mkdir(parents=True, exist_ok=True)
    if not available():
        return [(None, _estimate(t)) for t in texts]
    import numpy as np
    out = []
    for i, text in enumerate(texts):
        chunks = [r.audio.numpy() if hasattr(r.audio, "numpy") else r.audio
                  for r in _pipeline()(text, voice=VOICE, speed=SPEED)]
        audio = np.concatenate(chunks) if chunks else np.zeros(SR // 2, dtype="float32")
        # trim leading/trailing near-silence
        idx = np.where(np.abs(audio) > 0.01)[0]
        if len(idx):
            audio = audio[max(0, idx[0] - 600): idx[-1] + 2400]
        p = workdir / f"vo_{i:02d}.wav"
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        out.append((p, len(audio) / SR))
    return out
