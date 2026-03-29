# comfyui-promptcraft

A ComfyUI custom node for dynamic prompt generation.
Supports `{A|B}` variant syntax, `__wildcard__` file lookups, and `${var=value}` variables.

Built on the **ComfyUI V3 API** (`comfy_api.latest`). No required external dependencies (YAML support is optional).

> Japanese README: [README_jp.md](README_jp.md)

---

## Features

- **Variants** — `{A|B|C}` picks one option at random, with optional weights and nesting
- **Wildcards** — `__name__` pulls a random line from a `.txt` / `.json` / `.yaml` file
- **Variables** — `${var=!value}` declares a variable; `${var}` reuses it consistently across the prompt
- **Variable injection into wildcards** — set a variable in the prompt and wildcard files pick it up via `${var:default}`, overriding their own defaults
- **Show Text node** — displays the resolved prompt inline for quick inspection

---

## Installation

Clone or copy this repository into your `ComfyUI/custom_nodes/` folder and restart ComfyUI.

```
ComfyUI/
└── custom_nodes/
    └── comfyui-dynamic-prompts/
        ├── __init__.py
        ├── nodes.py
        ├── parser.py
        ├── pyproject.toml
        └── wildcards/
            └── example.txt
```

The **Promptcraft** category will appear in the Add Node menu with two nodes: **Random Prompts** and **Show Text**.

---

## Nodes

### Random Prompts

Resolves the template and outputs the resulting string.

| Input | Type | Description |
|-------|------|-------------|
| `Prompt Template` | STRING (multiline) | Template containing any combination of variant, wildcard, and variable syntax |
| `seed` | INT | Random seed. Set *control after generate* to `randomize` for a new result each run, or `fixed` for reproducible output |

| Output | Type | Description |
|--------|------|-------------|
| `text` | STRING | Fully resolved prompt |

### Show Text

Displays the resolved text on the node itself. Connect it after **Random Prompts** to inspect the output without leaving the graph. The text is also passed through as an output so the node can sit mid-chain (e.g. between Random Prompts and CLIPTextEncode).

| Input | Type | Description |
|-------|------|-------------|
| `text` | STRING | Text to display |

| Output | Type | Description |
|--------|------|-------------|
| `text` | STRING | Same text, passed through |

---

## Syntax Reference

### Variants `{A|B|C}`

Wrap options in `{` `}` and separate them with `|`. One option is chosen at random each run.

```
{red|green|blue} hair
```

→ `red hair` / `green hair` / `blue hair`

#### Weighted variants `{N::A|B}`

Prefix an option with `N::` to give it a relative weight (default weight is 1).

```
{3::common|rare|1::very rare}
```

`common` is 3× more likely than `rare`, and 9× more likely than `very rare`.

#### Nesting

Variants can be nested freely.

```
{bright {red|orange}|dark {blue|purple}}
```

→ `bright red` / `bright orange` / `dark blue` / `dark purple`

---

### Wildcards `__name__`

Replaces `__name__` with a random line from the matching file under the `wildcards/` folder.

```
a __color__ __animal__
```

Reads one line each from `wildcards/color.txt` and `wildcards/animal.txt`.

#### Subdirectories

Use `/` to reference files in subdirectories.

```
__characters/female__
```

→ reads from `wildcards/characters/female.txt`

#### File formats

Place wildcard files anywhere inside the `wildcards/` folder.

**`.txt`** (recommended) — one candidate per line; lines starting with `#` are comments

```
# color.txt
red
green
blue
dark blue
```

**`.json`** — array of strings

```json
["red", "green", "blue"]
```

**`.yaml` / `.yml`** — list of strings (requires `PyYAML`)

```yaml
- red
- green
- blue
```

#### Syntax inside wildcard files

Each line in a wildcard file can itself contain variants or variables.

```
# outfit.txt
{casual|formal} ${color:white} shirt
${season:summer} dress
```

---

### Variables `${var=value}` / `${var}`

Variables let you lock in a random choice once and reuse it consistently throughout the prompt, or pass values into wildcard files.

#### Immediate evaluation `!` — recommended

The `!` flag evaluates the value exactly once at declaration time. Every subsequent reference returns the same result.

```
${h=!{red|blue|pink}} ${e=!{brown|green}}
hanami_ume, (${h}_hair:1.05), medium_hair, one_side_up, ${e}_eyes,
```

→ `hanami_ume, (red_hair:1.05), medium_hair, one_side_up, brown_eyes,`

No matter how many times `${h}` appears, the colour is always the same.

#### Deferred evaluation (no `!`)

Without `!`, the expression is re-evaluated on every reference, so each use can produce a different value.

```
${adj={big|small}} A ${adj} cat and a ${adj} dog
```

→ could produce `big cat` and `small dog` (independently random)

#### Conditional assignment `?=`

Assigns only when the variable is **not yet set**. Useful for providing defaults inside wildcard files.

```
${color?=!white}
```

If `${color=!red}` was declared earlier (e.g. in the main prompt), `white` is ignored. Otherwise it takes effect.

#### Default-value access `${var:default}`

Returns the variable's value if set, or the default if the variable is undeclared.

```
${season:summer} outfit
```

→ uses `summer` if `season` has not been declared.

---

### Variable injection into wildcards

Declare variables in the prompt and wildcard files can reference them with defaults — the prompt-level value overrides the file's own default.

```
# wildcards/seasonal_outfit.txt
${season:summer} dress
${season:summer} coat
${color:white} blouse
```

```
# Prompt
${season=!winter}${color=!blue} a person wearing __seasonal_outfit__
```

→ `a person wearing winter dress`

Without the variable declarations, the wildcard files' own defaults (`summer`, `white`) apply instead. This is not possible with the original [comfyui-dynamicprompts](https://github.com/adieyal/comfyui-dynamicprompts) extension.

---

### Combining everything

All syntax can be mixed freely.

```
${h=!{red|pink|blonde}} ${e=!__eye_colors__}
1girl, (${h}_hair:1.1), ${e}_eyes, wearing {casual|formal} __tops__, __bottoms__
```

---

## Syntax Quick Reference

| Syntax | Description |
|--------|-------------|
| `{A\|B\|C}` | Pick one option at random |
| `{2::A\|B}` | Weighted pick (A is twice as likely) |
| `{A\|{B\|C}}` | Nesting |
| `__name__` | Random line from `wildcards/name.txt` |
| `__dir/name__` | Wildcard in a subdirectory |
| `${v=!val}` | Declare variable — immediate (value is fixed) |
| `${v=val}` | Declare variable — deferred (re-evaluated each use) |
| `${v?=!val}` | Declare variable — only if not already set |
| `${v}` | Read variable |
| `${v:default}` | Read variable, fall back to default if undeclared |

---

## Requirements

- ComfyUI 0.18.0 or later (V3 API)
- Python 3.10 or later
- `PyYAML` — optional, only needed for `.yaml` wildcard files

## License

MIT
