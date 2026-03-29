# comfyui-promptcraft

ComfyUI 向けの動的プロンプト生成カスタムノードです。
`{A|B}` バリアント構文、`__wildcard__` ワイルドカード、`${var=value}` 変数をサポートします。

ComfyUI V3 API（`comfy_api.latest`）準拠で実装されており、外部ライブラリへの依存はありません（YAML サポートは任意）。

---

## インストール

`ComfyUI/custom_nodes/` 以下にこのリポジトリを配置するだけです。

```
ComfyUI/
└── custom_nodes/
    └── comfyui-promptcraft/
        ├── __init__.py
        ├── nodes.py
        ├── parser.py
        ├── pyproject.toml
        ├── js/
        │   └── show_text.js
        └── wildcards/
            └── example.txt
```

ComfyUI を再起動すると **Promptcraft** カテゴリに **Random Prompts** と **Show Text** ノードが追加されます。

---

## ノード一覧

### Random Prompts

テンプレートを解決してプロンプト文字列を出力します。

| 入力 | 型 | 説明 |
|------|----|------|
| `Prompt Template` | STRING (multiline) | 構文を含むプロンプトテンプレート |
| `seed` | INT | 乱数シード。`control after generate` を `randomize` にすると毎回変化 |

| 出力 | 型 | 説明 |
|------|----|------|
| `text` | STRING | 解決済みプロンプト |

### Show Text

解決済みテキストをノード上に表示します。`Random Prompts` の出力を繋ぐと結果をその場で確認できます。
出力ポートもあるので CLIPTextEncode 等へのチェーン接続も可能です。

| 入力 | 型 | 説明 |
|------|----|------|
| `text` | STRING | 接続専用（テキストウィジェットなし）— 他ノードからワイヤーで繋ぐ |

| 出力 | 型 | 説明 |
|------|----|------|
| `text` | STRING | 入力と同じテキスト（パススルー）|

---

## 構文リファレンス

### コメント `#`

`#` から行末までの内容はコメントとして扱われ、出力に含まれません。バリアントブロックの内部を含め、テンプレートのどこでも使用できます。

```
{
red|
# green は一時的に無効|
blue
} hair
```

→ `red hair` または `blue hair`（`green` は選ばれない）

> **注意:** `${...}` 変数宣言の内部に `#` コメントを書かないでください。コメントは閉じ `}` の後に書いてください：
> ```
> ${color=!red} # 色を選択
> ```

構文エラー（`{` の未閉鎖、`__` の不整合など）がある場合、**Random Prompts** は実行前にすべてのエラーをリストアップしてワークフローの実行を停止します。

---

### バリアント `{A|B|C}`

`{` と `}` で囲み、`|` で選択肢を区切ります。実行のたびにランダムに1つ選択されます。

```
{red|green|blue} hair
```

出力例: `red hair` / `green hair` / `blue hair`

#### 複数回抽出と重複なし抽出 `{n$$A|B}` / `{!n$$A|B}`

選択肢の中から指定した回数だけ抽出することができます。

- `{2$$A|B|C}` : 2回抽出します（重複あり。例：`A, A` や `B, C`）。
- `{!2$$A|B|C}` : 先頭に `!` を付けると、**絶対に重複しない**ように抽出します（例：`A, C`）。
- `{2$$ and $$A|B|C}` : 出力を指定した文字（この場合は ` and `）で結合します。デフォルトは `, ` です。

#### 重み付き選択 `{N::A|B}`

選択肢の前に `N::` を付けると重みを指定できます。

```
{3::common|rare|1::very rare}
```

`common` が3倍、`very rare` が1/3の確率で選ばれます（未指定は重み1）。

#### ネスト

バリアントはネストできます。

```
{bright {red|orange}|dark {blue|purple}}
```

出力例: `bright red` / `bright orange` / `dark blue` / `dark purple`

---

### ワイルドカード `__name__`

`__` で囲まれた名前を、対応するファイルからランダムに選んだ1行で置換します。

```
a __color__ __animal__
```

`wildcards/color.txt` と `wildcards/animal.txt` から1行ずつ選択されます。

#### プロンプト全体での重複なし抽出 `__!name__`

ファイル名の前に `!` を付けると、「このプロンプト全体を通して、まだ一度も選ばれていない行」を優先して抽出します。

```
__!color__ and __!color__
```

→ 同じファイルを参照しても、確実に異なる2つの色が出力されます（例：`red and blue`。`red and red` にはなりません）。

#### サブディレクトリ

`/` でサブディレクトリを指定できます。

```
__characters/female__
```

→ `wildcards/characters/female.txt` を参照

#### ファイル形式

ワイルドカードファイルは `wildcards/` フォルダに置いてください。

**`.txt`**（推奨）: 1行1候補、`#` で始まる行はコメント

```
# color.txt
red
green
blue
dark blue
```

**`.json`**: 文字列の配列

```json
["red", "green", "blue"]
```

**`.yaml` / `.yml`**: 文字列のリスト（`PyYAML` が必要）

```yaml
- red
- green
- blue
```

#### ワイルドカード内にバリアント・変数を書く

ワイルドカードファイルの各行にも構文を書けます。

```
# outfit.txt
{casual|formal} ${color:white} shirt
${season:summer} dress
```

---

### 変数 `${var=value}` / `${var}`

変数を使うと、同じプロンプト内で値を共有したり、ワイルドカードにデフォルト値を渡せます。

#### 即時評価（`!` あり）— 推奨

`!` を付けると、宣言時に1度だけ評価され、以降の参照はすべて同じ値を返します。

```
${h=!{red|blue|pink}} ${e=!{brown|green}}
hanami_ume, (${h}_hair:1.05), medium_hair, one_side_up, ${e}_eyes,
```

出力例: `hanami_ume, (red_hair:1.05), medium_hair, one_side_up, brown_eyes,`

`${h}` を何度参照しても常に同じ色になります。

#### 遅延評価（`!` なし）

`!` なしの場合、参照のたびに式が再評価されます。

```
${adj={big|small}} A ${adj} cat and a ${adj} dog
```

`${adj}` ごとに独立してランダム選択されるため、`big cat` と `small dog` になる可能性があります。

#### 保護代入 `?=`

変数がまだ設定されていない場合のみ代入します。ワイルドカードファイルでのデフォルト定義に便利です。

```
${color?=!white}
```

外部から `${color=!red}` が宣言されていればそちらが優先され、未宣言なら `white` が使われます。

#### デフォルト値付き参照 `${var:default}`

変数が未宣言の場合にデフォルト値を使います。

```
${season:summer} outfit
```

`season` が宣言済みならその値、未宣言なら `summer` になります。

---

### 変数とワイルドカードの連携

変数をプロンプト側で宣言し、ワイルドカード側でデフォルト付き参照を書くことで、
**ワイルドカードに外部から値を「注入」する**ことができます。

```
# wildcards/seasonal_outfit.txt
${season:summer} dress
${season:summer} coat
${color:white} blouse
```

```
# プロンプト
${season=!winter}${color=!blue} a person wearing __seasonal_outfit__
```

出力例: `a person wearing winter dress`（`summer` ではなく `winter` が使われる）

変数を宣言しない場合はファイル内のデフォルト（`summer`）が使われます。

---

### 構文の組み合わせ

すべての構文は自由に組み合わせられます。

```
${h=!{red|pink|blonde}} ${e=!__eye_colors__}
1girl, (${h}_hair:1.1), ${e}_eyes, wearing {casual|formal} __tops__, __bottoms__
```

---

## 構文早見表

| 構文 | 説明 |
|------|------|
| `{A\|B\|C}` | ランダムに1つ選択 |
| `{n$$A\|B}` | 複数回抽出（例：`{2$$A\|B}`） |
| `{!n$$A\|B}` | 重複なし複数回抽出 |
| `{2::A\|B}` | 重み付き選択（A が2倍の確率）|
| `{A\|{B\|C}}` | ネスト |
| `__name__` | ワイルドカード（`wildcards/name.txt`）|
| `__!name__` | 重複なしワイルドカード（プロンプト全体でユニーク） |
| `__dir/name__` | サブディレクトリのワイルドカード |
| `${v=!val}` | 変数宣言・即時評価（固定）|
| `${v=val}` | 変数宣言・遅延評価（参照ごとに再評価）|
| `${v?=!val}` | 変数宣言・未設定時のみ（デフォルト定義）|
| `${v}` | 変数参照 |
| `${v:default}` | 変数参照・未宣言時はデフォルト値 |
| `# コメント` | コメント — 行末まで無視される |

---

## ファイル構成

```
comfyui-promptcraft/
├── __init__.py      # comfy_entrypoint（V3 ノード登録）
├── nodes.py         # ComfyUI ノード定義
├── parser.py        # パーサー本体
├── pyproject.toml   # メタデータ
├── js/
│   └── show_text.js # Show Text フロントエンド拡張
└── wildcards/
    └── example.txt  # サンプルワイルドカード
```

## 動作要件

- ComfyUI 0.18.0 以降（V3 API）
- Python 3.10 以降
- YAML ファイルを使う場合は `PyYAML`（任意）
