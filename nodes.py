"""
ComfyUI V3 node definitions for dynamic prompt generation.
"""

from __future__ import annotations

from pathlib import Path
from typing_extensions import override

from comfy_api.latest import ComfyExtension, io, ui

from . import parser

_WILDCARDS_DIR = Path(__file__).parent / "wildcards"


class RandomPromptsNode(io.ComfyNode):
    """
    Resolve ``{A|B|C}`` variant syntax and ``__wildcard__`` tokens in a
    prompt template and output the resulting string.

    Syntax
    ------
    ``{A|B|C}``
        Pick one option at random.

    ``{2::A|B}``
        Weighted pick — A is twice as likely as B.

    ``{A|{B|C}}``
        Nesting is supported.

    ``__name__``
        Replace with a random line from ``wildcards/name.txt``
        (also ``.json`` / ``.yaml``).

    ``__subdir/name__``
        Wildcard in a subdirectory.
    """

    @classmethod
    @override
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="PCRandomPrompts",
            display_name="Random Prompts",
            category="Promptcraft",
            description=(
                "Resolve {A|B|C} variants and __wildcard__ tokens in a prompt template.\n"
                "\n"
                "Syntax:\n"
                "  {A|B|C}      — pick one option at random\n"
                "  {2::A|B}     — weighted pick (A is twice as likely)\n"
                "  {A|{B|C}}    — nesting supported\n"
                "  __name__     — random value from wildcards/name.txt\n"
                "  __dir/name__ — wildcard in a subdirectory"
            ),
            search_aliases=["dynamic prompts", "random prompt", "wildcard"],
            inputs=[
                io.String.Input(
                    "text",
                    display_name="Prompt Template",
                    multiline=True,
                    dynamic_prompts=False,
                    default="",
                    tooltip=(
                        "Prompt template.\n"
                        "  {A|B|C}  — pick one at random\n"
                        "  __name__ — wildcard from file"
                    ),
                ),
                io.Int.Input(
                    "seed",
                    default=0,
                    min=0,
                    max=0xFFFFFFFFFFFFFFFF,
                    control_after_generate=io.ControlAfterGenerate.randomize,
                    tooltip=(
                        "Random seed.\n"
                        "Set 'control after generate' to 'fixed' for reproducible results."
                    ),
                ),
            ],
            outputs=[
                io.String.Output(
                    "text",
                    display_name="Resolved Prompt",
                    tooltip="The prompt template with all variants and wildcards resolved.",
                ),
            ],
        )

    @classmethod
    @override
    def execute(cls, text: str, seed: int) -> io.NodeOutput:
        result = parser.generate(text, seed, _WILDCARDS_DIR)
        return io.NodeOutput(result)


class ShowTextNode(io.ComfyNode):
    """
    入力テキストをノード上に表示し、そのまま下流へ流します。
    Random Prompts ノードの出力を確認するのに使います。
    """

    @classmethod
    @override
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="PCShowText",
            display_name="Show Text",
            category="Promptcraft",
            description="テキストをノード上に表示します。入力をそのまま出力に流すのでチェーン接続も可能です。",
            is_output_node=True,
            inputs=[
                io.String.Input(
                    "text",
                    display_name="Text",
                    multiline=True,
                    dynamic_prompts=False,
                    tooltip="表示するテキスト。Random Prompts の出力を繋いでください。",
                ),
            ],
            outputs=[
                io.String.Output(
                    "text",
                    display_name="Text",
                    tooltip="入力と同じテキスト。下流のノードへチェーンできます。",
                ),
            ],
        )

    @classmethod
    @override
    def execute(cls, text: str) -> io.NodeOutput:
        return io.NodeOutput(text, ui=ui.PreviewText(text))


class DynamicPromptsExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [RandomPromptsNode, ShowTextNode]
