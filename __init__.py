from .nodes import DynamicPromptsExtension

WEB_DIRECTORY = "./js"

async def comfy_entrypoint() -> DynamicPromptsExtension:
    return DynamicPromptsExtension()
