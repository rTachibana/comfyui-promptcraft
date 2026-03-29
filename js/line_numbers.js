import { app } from "../../scripts/app.js";

const _LINE_NUMBER_NODES = new Set(["PCRandomPrompts", "PCRandomPromptsDebug"]);

function setupLineNumbers(textarea) {
    const parent = textarea.parentNode;
    if (!parent || parent.dataset.lineNumbersAttached) return;
    parent.dataset.lineNumbersAttached = "1";

    // Wrapper: gutter | textarea を横並びにする
    const wrapper = document.createElement("div");
    wrapper.style.cssText = "display:flex;width:100%;height:100%;";

    const gutter = document.createElement("div");
    gutter.style.cssText = [
        "padding: 4px 6px 4px 4px",
        "color: #666",
        "font-family: monospace",
        "font-size: inherit",
        "line-height: inherit",
        "white-space: pre",
        "user-select: none",
        "text-align: right",
        "min-width: 2.2em",
        "overflow: hidden",
        "flex-shrink: 0",
        "border-right: 1px solid #444",
        "background: rgba(0,0,0,0.25)",
    ].join(";");

    parent.insertBefore(wrapper, textarea);
    wrapper.appendChild(gutter);
    wrapper.appendChild(textarea);

    textarea.style.flexGrow = "1";
    textarea.style.width = "0";        // flexbox に任せる
    textarea.style.resize = "none";    // wrapper が幅を管理するので無効化

    function update() {
        const count = textarea.value.split("\n").length;
        gutter.textContent = Array.from({ length: count }, (_, i) => i + 1).join("\n");
        // ガターの行高をテキストエリアに合わせる
        gutter.style.fontSize = getComputedStyle(textarea).fontSize;
        gutter.style.lineHeight = getComputedStyle(textarea).lineHeight;
    }

    textarea.addEventListener("input", update);
    textarea.addEventListener("scroll", () => {
        gutter.scrollTop = textarea.scrollTop;
    });

    update();
}

app.registerExtension({
    name: "Promptcraft.LineNumbers",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!_LINE_NUMBER_NODES.has(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, []);

            // "text" ウィジェット（Prompt Template）の textarea を探す
            const w = this.widgets?.find((w) => w.name === "text");
            const el = w?.element ?? w?.inputEl;
            if (el) {
                setupLineNumbers(el);
            } else if (w) {
                // 稀に element がまだ DOM に追加されていない場合の保険
                requestAnimationFrame(() => {
                    const delayed = w.element ?? w.inputEl;
                    if (delayed) setupLineNumbers(delayed);
                });
            }
        };
    },
});
