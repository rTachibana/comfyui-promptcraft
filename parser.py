"""
Dynamic prompts parser.

Supported syntax
----------------
{A|B|C}
    Randomly pick one option.

{2::A|B}
    Weighted pick — A is twice as likely as B.

{A|{B|C}}
    Nesting is supported.

__name__
    Replace with a random line from wildcards/name.txt (also .json/.yaml).

__dir/name__
    Wildcard in a subdirectory.

${var=!value}
    Declare variable ``var`` with IMMEDIATE evaluation.
    The value is resolved once at declaration time; every reference to
    ``${var}`` returns that same result.
    Example: ${h=!{red|blue}} → always the same colour throughout the prompt.

${var=value}
    Declare variable ``var`` with DEFERRED evaluation.
    The value is re-evaluated fresh on every ``${var}`` reference.
    Example: ${h={red|blue}} → may produce different colours at each use.

${var?=!value}
    Declare variable ``var`` only if it is NOT already set.
    Useful for providing defaults in reusable templates.

${var}
    Read variable ``var`` (error if not declared).

${var:default}
    Read variable ``var``, or use ``default`` if it is not declared.

Notes
-----
- Variable declarations produce no output (they are replaced by "").
- Variable and variant/wildcard syntax can be freely mixed.
- Variables are resolved before {A|B} expansion so that ``${var=!{A|B}}``
  works correctly: the variant is expanded once inside the declaration.
"""

from __future__ import annotations

import json
import re
import random
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_VARIANT_PASSES = 200
_MAX_RESOLVE_ROUNDS = 20

_VARIANT_RE  = re.compile(r"(?<!\$)\{([^{}]*)\}")
_WILDCARD_RE = re.compile(r"__([a-zA-Z0-9_/\\.-]+)__")

# Matches the *inner* content of ${…} as a declaration.
# Groups: name, preserve ('?' or ''), immediate ('!' or ''), value
_VAR_DECL_INNER_RE = re.compile(
    r"^(?P<name>[a-zA-Z_][a-zA-Z0-9_-]*)(?P<preserve>\??)=(?P<immediate>!?)(?P<value>.*)",
    re.DOTALL,
)

# Validates a bare variable name (used when parsing accesses).
_VAR_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")


# ---------------------------------------------------------------------------
# Wildcard file loading
# ---------------------------------------------------------------------------

def _load_txt(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _load_json(text: str) -> list[str]:
    data = json.loads(text)
    if isinstance(data, list):
        return [str(v) for v in data if str(v).strip()]
    return []


def _load_yaml(text: str) -> list[str]:
    if not _HAS_YAML:
        return []
    data = _yaml.safe_load(text)
    if isinstance(data, list):
        return [str(v) for v in data if str(v).strip()]
    return []


def load_wildcard_file(path: Path) -> list[str]:
    """Load wildcard values from a file. Returns an empty list on any error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    ext = path.suffix.lower()
    if ext == ".txt":
        return _load_txt(text)
    if ext == ".json":
        return _load_json(text)
    if ext in (".yaml", ".yml"):
        return _load_yaml(text)
    return []


def find_wildcard(name: str, wildcards_dir: Path) -> list[str]:
    """
    Find and load values for a wildcard name.
    ``name`` may contain '/' or '\\' as subdirectory separators.
    Returns an empty list if nothing is found.
    """
    parts = name.replace("\\", "/").split("/")
    rel = Path(*parts)
    for ext in (".txt", ".yaml", ".yml", ".json"):
        candidate = wildcards_dir / (str(rel) + ext)
        if candidate.is_file():
            values = load_wildcard_file(candidate)
            if values:
                return values
    return []


# ---------------------------------------------------------------------------
# Variant resolution  {A|B|C}
# ---------------------------------------------------------------------------

def _weighted_choice(raw_options: list[str], rng: random.Random) -> str:
    """
    Pick one option, honouring an ``N::text`` weight prefix.
    e.g. ``["2::cat", "dog"]`` → cat has 2× the probability of dog.
    """
    items: list[str] = []
    weights: list[float] = []
    for opt in raw_options:
        if "::" in opt:
            prefix, _, body = opt.partition("::")
            try:
                items.append(body)
                weights.append(float(prefix))
                continue
            except ValueError:
                pass
        items.append(opt)
        weights.append(1.0)
    return rng.choices(items, weights=weights, k=1)[0]


def resolve_variants(text: str, rng: random.Random) -> str:
    """Replace all {A|B|C} groups with a random choice (innermost first)."""
    for _ in range(_MAX_VARIANT_PASSES):
        m = _VARIANT_RE.search(text)
        if not m:
            break
        options = [o.strip() for o in m.group(1).split("|")]
        chosen = _weighted_choice(options, rng)
        text = text[: m.start()] + chosen + text[m.end() :]
    return text


# ---------------------------------------------------------------------------
# Wildcard resolution  __name__
# ---------------------------------------------------------------------------

def resolve_wildcards(
    text: str, rng: random.Random, wildcards_dir: Path
) -> tuple[str, bool]:
    """
    Replace ``__name__`` tokens with a random value from the matching file.
    Returns ``(resolved_text, any_replaced)``.
    Unknown wildcards are left unchanged.
    """
    replaced = False

    def _replace(m: re.Match) -> str:
        nonlocal replaced
        values = find_wildcard(m.group(1), wildcards_dir)
        if values:
            replaced = True
            return rng.choice(values)
        return m.group(0)

    return _WILDCARD_RE.sub(_replace, text), replaced


# ---------------------------------------------------------------------------
# Variable resolution  ${var=value}  /  ${var}
# ---------------------------------------------------------------------------

def _find_variable_end(text: str, dollar_pos: int) -> int:
    """
    Given the index of the ``$`` in ``${…}``, return the index of the
    matching closing ``}``, counting nested braces.
    Returns -1 if no match is found.
    """
    if dollar_pos + 1 >= len(text) or text[dollar_pos + 1] != "{":
        return -1
    depth = 1
    i = dollar_pos + 2
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


def _resolve_expression(
    expr: str,
    rng: random.Random,
    wildcards_dir: Path,
    context: dict[str, Any],
) -> str:
    """
    Fully resolve *expr*: variables, then variants, then wildcards.
    Called recursively for immediate variable values and deferred accesses.
    """
    text = expr
    for _ in range(_MAX_RESOLVE_ROUNDS):
        prev = text
        text = resolve_variables(text, rng, wildcards_dir, context)
        text = resolve_variants(text, rng)
        text, _ = resolve_wildcards(text, rng, wildcards_dir)
        if text == prev:
            break
    return text


def resolve_variables(
    text: str,
    rng: random.Random,
    wildcards_dir: Path,
    context: dict[str, Any],
) -> str:
    """
    Process all ``${…}`` tokens in *text* left-to-right, updating *context*.

    - Declarations (``${var=value}``) are removed from the output.
    - Accesses (``${var}`` / ``${var:default}``) are replaced by their value.
    - Unknown variable accesses are left unchanged.
    """
    result: list[str] = []
    pos = 0

    while pos < len(text):
        idx = text.find("${", pos)
        if idx == -1:
            result.append(text[pos:])
            break

        # Text before this token
        result.append(text[pos:idx])

        # Find the closing } that matches the { in ${
        end = _find_variable_end(text, idx)
        if end == -1:
            # Unmatched ${ — emit the $ literally and retry from after it
            result.append("$")
            pos = idx + 1
            continue

        inner = text[idx + 2 : end]  # content between ${ and }
        pos = end + 1

        # ── Try to parse as a DECLARATION ────────────────────────────────
        m = _VAR_DECL_INNER_RE.match(inner)
        if m:
            name      = m.group("name")
            preserve  = bool(m.group("preserve"))   # True if ?= was used
            immediate = bool(m.group("immediate"))   # True if ! was present
            value_tpl = m.group("value")

            # ?= : only assign if the variable is not yet in context
            if preserve and name in context:
                # Leave variable as-is; declaration produces no output
                continue

            if immediate:
                # Evaluate the value right now and store the result string
                context[name] = _resolve_expression(value_tpl, rng, wildcards_dir, context)
            else:
                # Store the raw template; re-evaluate on every access
                context[name] = ("deferred", value_tpl)

            # Declarations always produce no output
            continue

        # ── Parse as an ACCESS ────────────────────────────────────────────
        if ":" in inner:
            colon = inner.index(":")
            name = inner[:colon]
            default_tpl: str | None = inner[colon + 1 :]
        else:
            name = inner
            default_tpl = None

        # Validate the name; leave invalid tokens unchanged
        if not _VAR_NAME_RE.match(name):
            result.append("${" + inner + "}")
            continue

        if name in context:
            value = context[name]
            if isinstance(value, tuple) and value[0] == "deferred":
                # Re-evaluate the stored template each time
                result.append(_resolve_expression(value[1], rng, wildcards_dir, context))
            else:
                result.append(str(value))
        elif default_tpl is not None:
            result.append(_resolve_expression(default_tpl, rng, wildcards_dir, context))
        else:
            # Variable not declared and no default — leave token unchanged
            result.append("${" + inner + "}")

    return "".join(result)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate(text: str, seed: int, wildcards_dir: Path) -> str:
    """
    Fully resolve *text* using the given *seed* and *wildcards_dir*.

    Resolution order per iteration:
    1. Variables  (${var=…} declarations, ${var} accesses)
    2. Variants   ({A|B|C})
    3. Wildcards  (__name__)

    Variables are resolved first so that ``${var=!{A|B}}`` works as expected:
    the variant inside the declaration is evaluated once and locked in.

    The loop repeats until the text is stable or the iteration limit is hit,
    allowing wildcard values to contain variant syntax, etc.
    """
    rng = random.Random(seed)
    context: dict[str, Any] = {}

    for _ in range(_MAX_RESOLVE_ROUNDS):
        prev = text
        text = resolve_variables(text, rng, wildcards_dir, context)
        text = resolve_variants(text, rng)
        text, _ = resolve_wildcards(text, rng, wildcards_dir)
        if text == prev:
            break

    return text
