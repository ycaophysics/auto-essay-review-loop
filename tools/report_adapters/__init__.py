"""Report adapter registry and Jinja2 environment."""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from . import _helpers
from .model import (
    ReportCheck,
    ReportItem,
    ReportRound,
    ReportRun,
    ReportScore,
    ReportTrace,
)

if TYPE_CHECKING:
    pass

_REGISTRY: dict[str, Callable[[Path], ReportRun]] = {}

# Belt-and-suspenders path inference when RUN.json lacks skill (migration race).
_SKILL_PATH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"review-stage/outbound/"), "linkedin-outbound"),
    (re.compile(r"review-stage/essay/"), "essay"),
    (re.compile(r"review-stage/blog/"), "blog"),
    (re.compile(r"review-stage/cv/"), "cv"),
    (re.compile(r"review-stage/slides/"), "slides"),
    (re.compile(r"review-stage/business-plan/"), "business-plan"),
    (re.compile(r"review-stage/application/"), "application"),
    (re.compile(r"review-stage/social/"), "social"),
    (re.compile(r"review-stage/linkedin/"), "linkedin"),
    (re.compile(r"review-stage/market-research/"), "market-research"),
]


def register(skill_name: str):
    """Decorator: register build(run_dir) -> ReportRun under skill_name."""

    def decorator(fn: Callable[[Path], ReportRun]):
        _REGISTRY[skill_name] = fn
        return fn

    return decorator


def get_adapter(skill: str) -> Callable[[Path], ReportRun] | None:
    return _REGISTRY.get(skill)


def list_adapters() -> list[str]:
    return sorted(_REGISTRY.keys())


def infer_skill_from_path(run_dir: Path) -> str | None:
    """Infer skill key from run_dir path when RUN.json lacks skill field."""
    path_str = str(run_dir.resolve()).replace("\\", "/")
    for pattern, skill in _SKILL_PATH_PATTERNS:
        if pattern.search(path_str):
            return skill
    return None


def _autoescape_with_mask(value) -> Markup:
    return Markup(_helpers.mask_secrets(escape(str(value))))


def make_jinja_env(templates_dir: Path) -> Environment:
    """Jinja2 environment: autoescape ON, mask_secrets chained after escape."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    env.filters["mask_secrets"] = _helpers.mask_secrets
    env.policies["html.autoescape"] = _autoescape_with_mask
    return env


def _auto_import_adapters() -> None:
    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name.startswith("_"):
            continue
        if module_info.name in ("model",):
            continue
        importlib.import_module(f"{__name__}.{module_info.name}")


_auto_import_adapters()

__all__ = [
    "ReportCheck",
    "ReportItem",
    "ReportRound",
    "ReportRun",
    "ReportScore",
    "ReportTrace",
    "get_adapter",
    "infer_skill_from_path",
    "list_adapters",
    "make_jinja_env",
    "register",
]
