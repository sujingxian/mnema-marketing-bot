"""Video formats for the format test (marketing/ZERO_COST_AGENT_PLAN.md §二).

Every format is ``build(item, out, music, workdir=None) -> Path``: it renders one emotion-series
script (HOOK → TURN → LINE) to a 1080×1920 MP4. The same script is rendered in several formats
per day and posted with identical captions, so the format is the only variable being tested.

Add a renderer here and list its code in plan.ENABLED_FORMATS to put it into the rotation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Format:
    code: str
    name: str
    voiced: bool
    build: Callable[..., Path]


def _f1(item: dict, out: Path, music: Path, workdir: Path | None = None) -> Path:
    from .. import emotion_v2          # paper + handwriting + voice (the original bot look)
    return emotion_v2.build(item, out, music, workdir)


def _f2(item: dict, out: Path, music: Path, workdir: Path | None = None) -> Path:
    from . import ink_serif
    return ink_serif.build(item, out, music, workdir)


def _f3(item: dict, out: Path, music: Path, workdir: Path | None = None) -> Path:
    from . import kinetic_bold
    return kinetic_bold.build(item, out, music, workdir)


FORMATS: dict[str, Format] = {
    "F1": Format("F1", "paper-voice", True, _f1),
    "F2": Format("F2", "ink-serif", False, _f2),
    "F3": Format("F3", "kinetic-bold", True, _f3),
}
