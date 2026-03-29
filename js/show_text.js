import { app } from "../../scripts/app.js";
import { ComfyWidgets } from "../../scripts/widgets.js";

const _PREVIEW_NODES = new Set(["PCShowText", "PCRandomPromptsDebug"]);

app.registerExtension({
    name: "Promptcraft.ShowText",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (!_PREVIEW_NODES.has(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, []);

            const { widget } = ComfyWidgets["STRING"](
                this,
                "preview_text",
                ["STRING", { multiline: true }],
                app
            );
            widget.label = "Preview";
            widget.element.readOnly = true;
            widget.options.read_only = true;
            widget.serialize = false;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            onExecuted?.apply(this, [message]);

            const w = this.widgets?.find((w) => w.name === "preview_text");
            if (!w) return;

            const text = message.text ?? "";
            w.value = Array.isArray(text) ? text.join("\n\n") : text;
        };
    },
});
