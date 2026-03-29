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

# comment
    Lines (or line portions) starting with # are treated as comments and
    stripped from the output.  Inside a variant group, options that reduce
    to empty after comment stripping are excluded from the draw.

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
_WILDCARD_RE = re.compile(r"__(!?)([a-zA-Z0-9_/\\.-]+)__")

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
# Syntax validation
# ---------------------------------------------------------------------------

def _src_location(text: str, pos: int) -> str:
    """Return a human-readable 'line N, col N: …snippet…' string for *pos*."""
    line = text[:pos].count("\n") + 1
    col  = pos - text[:pos].rfind("\n")
    s = max(0, pos - 18)
    e = min(len(text), pos + 18)
    snippet = text[s:e].replace("\n", "↵")
    if s > 0:
        snippet = "…" + snippet
    if e < len(text):
        snippet = snippet + "…"
    return f"line {line}, col {col}: {snippet!r}"


def _check_braces(text: str) -> list[str]:
    """Report unmatched ``{`` / ``}`` in variant syntax (skips ``${…}`` blocks)."""
    errors: list[str] = []
    stack: list[int] = []
    i = 0
    while i < len(text):
        if text[i] == "$" and i + 1 < len(text) and text[i + 1] == "{":
            end = _find_variable_end(text, i)
            if end == -1:
                errors.append(f"Unclosed '${{' at {_src_location(text, i)}")
                i += 2
            else:
                i = end + 1
            continue
        if text[i] == "{":
            stack.append(i)
        elif text[i] == "}":
            if stack:
                stack.pop()
            else:
                errors.append(f"Unexpected '}}' at {_src_location(text, i)}")
        i += 1
    for pos in stack:
        errors.append(f"Unclosed '{{' at {_src_location(text, pos)}")
    return errors


def _check_wildcards(text: str) -> list[str]:
    """Report ``__`` markers that are not part of a valid ``__name__`` wildcard."""
    valid_positions: set[int] = set()
    for m in _WILDCARD_RE.finditer(text):
        valid_positions.add(m.start())       # opening __
        valid_positions.add(m.end() - 2)    # closing __
    errors: list[str] = []
    for m in re.finditer(r"__", text):
        if m.start() not in valid_positions:
            errors.append(f"Unclosed or malformed wildcard at {_src_location(text, m.start())}")
    return errors


def validate_syntax(text: str) -> list[str]:
    """
    Return a list of syntax error messages for *text*.
    An empty list means the text is valid.

    Comments (``#`` to end of line) are stripped before checking so that
    ``}`` or ``__`` appearing after ``#`` are not counted as closing tokens.
    """
    stripped = _strip_line_comments(text)
    return _check_braces(stripped) + _check_wildcards(stripped)


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------

def _strip_line_comments(text: str) -> str:
    """Remove ``#``-to-end-of-line comments from every line in *text*."""
    lines = []
    for line in text.splitlines():
        comment_pos = line.find("#")
        lines.append(line[:comment_pos] if comment_pos != -1 else line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Variant resolution  {A|B|C}
# ---------------------------------------------------------------------------

def _weighted_choice(raw_options: list[str], rng: random.Random) -> str:
    """
    Pick one option, honouring an ``N::text`` weight prefix.
    e.g. ``["2::cat", "dog"]`` → cat has 2× the probability of dog.

    Options that are empty (or become empty after comment stripping) are
    excluded from the draw.
    """
    items: list[str] = []
    weights: list[float] = []
    for opt in raw_options:
        clean = _strip_line_comments(opt).strip()
        if not clean:
            continue
        if "::" in clean:
            prefix, _, body = clean.partition("::")
            try:
                items.append(body)
                weights.append(float(prefix))
                continue
            except ValueError:
                pass
        items.append(clean)
        weights.append(1.0)
    if not items:
        return ""
    return rng.choices(items, weights=weights, k=1)[0]


def resolve_variants(
    text: str, rng: random.Random, wildcards_dir: Path, context: dict[str, Any]
) -> str:
    """Replace all {A|B|C} groups with a random choice (innermost first)."""
    for _ in range(_MAX_VARIANT_PASSES):
        m = _VARIANT_RE.search(text)
        if not m:
            break
            
        inner = m.group(1)
        parts = inner.split("$$")
        is_unique = False
        count = 1
        sep = ", "
        options_str = inner
        
        if len(parts) >= 2:
            prefix = parts[0].strip()
            is_valid_prefix = False
            if prefix.startswith("!") and prefix[1:].isdigit():
                is_unique = True
                count = int(prefix[1:])
                is_valid_prefix = True
            elif prefix.isdigit():
                count = int(prefix)
                is_valid_prefix = True
                
            if is_valid_prefix:
                if len(parts) == 2:
                    options_str = parts[1]
                elif len(parts) >= 3:
                    sep = parts[1]
                    options_str = "$$".join(parts[2:])
                    
        options = [o.strip() for o in options_str.split("|")]
        chosen_list = []
        
        if is_unique:
            seen = set()
            attempts = 0
            # Safety measure: allow max combinations of retries to avoid infinite loops
            # when requested count > available unique choices
            max_attempts = max(count * 50, 1000)
            while len(chosen_list) < count and attempts < max_attempts:
                attempts += 1
                raw_opt = _weighted_choice(options, rng)
                if not raw_opt:
                    break
                resolved = _resolve_expression(raw_opt, rng, wildcards_dir, context)
                if resolved and resolved not in seen:
                    seen.add(resolved)
                    chosen_list.append(resolved)
        else:
            for _ in range(count):
                raw_opt = _weighted_choice(options, rng)
                if not raw_opt:
                    break
                chosen_list.append(raw_opt)
                
        chosen_str = sep.join(chosen_list)
        text = text[: m.start()] + chosen_str + text[m.end() :]
    return text


# ---------------------------------------------------------------------------
# Wildcard resolution  __name__
# ---------------------------------------------------------------------------

def resolve_wildcards(
    text: str, rng: random.Random, wildcards_dir: Path, global_seen: set[str] = None
) -> tuple[str, bool]:
    """
    Replace ``__name__`` or ``__!name__`` tokens with a random value from the matching file.
    Returns ``(resolved_text, any_replaced)``.
    Unknown wildcards are left unchanged.
    """
    replaced = False

    def _replace(m: re.Match) -> str:
        nonlocal replaced
        is_unique = bool(m.group(1))
        wildcard_name = m.group(2)
        values = find_wildcard(wildcard_name, wildcards_dir)
        
        if values:
            replaced = True
            if is_unique and global_seen is not None:
                # filter values to only those not seen
                available = [v for v in values if v not in global_seen]
                if not available:
                    # fallback to all values if we run out of unique ones
                    available = values
                chosen = rng.choice(available)
                global_seen.add(chosen)
                return chosen
            else:
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
    global_seen = context.setdefault("__global_seen__", set())
    for _ in range(_MAX_RESOLVE_ROUNDS):
        prev = text
        text = resolve_variables(text, rng, wildcards_dir, context)
        text = resolve_variants(text, rng, wildcards_dir, context)
        text, _ = resolve_wildcards(text, rng, wildcards_dir, global_seen)
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
    global_seen = context.setdefault("__global_seen__", set())

    for _ in range(_MAX_RESOLVE_ROUNDS):
        prev = text
        text = resolve_variables(text, rng, wildcards_dir, context)
        text = resolve_variants(text, rng, wildcards_dir, context)
        text, _ = resolve_wildcards(text, rng, wildcards_dir, global_seen)
        if text == prev:
            break

    return _strip_line_comments(text)
