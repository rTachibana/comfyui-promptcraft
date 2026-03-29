from .nodes import DynamicPromptsExtension


async def comfy_entrypoint() -> DynamicPromptsExtension:
    return DynamicPromptsExtension()
