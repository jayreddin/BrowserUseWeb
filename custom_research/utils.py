import base64
import os
import time
from pathlib import Path
from typing import Dict, Optional

PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "azure_openai": "Azure OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "google": "Google"
}
    
# Predefined model names for common providers
model_names = {
    "anthropic": ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229"],
    "openai": ["gpt-4o", "gpt-4", "gpt-3.5-turbo", "o3-mini"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "google": ["gemini-2.0-flash-exp", "gemini-2.0-flash-thinking-exp", "gemini-1.5-flash-latest", "gemini-1.5-flash-8b-latest", "gemini-2.0-flash-thinking-exp-01-21"],
    "ollama": ["qwen2.5:7b", "llama2:7b", "deepseek-r1:14b", "deepseek-r1:32b"],
    "azure_openai": ["gpt-4o", "gpt-4", "gpt-3.5-turbo"],
    "mistral": ["pixtral-large-latest", "mistral-large-latest", "mistral-small-latest", "ministral-8b-latest"]
}

# Callback to update the model name dropdown based on the selected provider
def update_model_dropdown(llm_provider, api_key=None, base_url=None):
    pass

def handle_api_key_error(provider: str, env_var: str):
    pass

def encode_image(img_path):
    if not img_path:
        return None
    with open(img_path, "rb") as fin:
        image_data = base64.b64encode(fin.read()).decode("utf-8")
    return image_data


def get_latest_files(directory: str, file_types: list = ['.webm', '.zip']) -> Dict[str, Optional[str]]:
    """Get the latest recording and trace files"""
    latest_files: Dict[str, Optional[str]] = {ext: None for ext in file_types}
    
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        return latest_files

    for file_type in file_types:
        try:
            matches = list(Path(directory).rglob(f"*{file_type}"))
            if matches:
                latest = max(matches, key=lambda p: p.stat().st_mtime)
                # Only return files that are complete (not being written)
                if time.time() - latest.stat().st_mtime > 1.0:
                    latest_files[file_type] = str(latest)
        except Exception as e:
            print(f"Error getting latest {file_type} file: {e}")
            
    return latest_files

async def capture_screenshot(browser_context):
    """Capture and encode a screenshot"""
    # Extract the Playwright browser instance
    playwright_browser = browser_context.browser.playwright_browser  # Ensure this is correct.

    # Check if the browser instance is valid and if an existing context can be reused
    if playwright_browser and playwright_browser.contexts:
        playwright_context = playwright_browser.contexts[0]
    else:
        return None

    # Access pages in the context
    pages = None
    if playwright_context:
        pages = playwright_context.pages

    # Use an existing page or create a new one if none exist
    if pages:
        active_page = pages[0]
        for page in pages:
            if page.url != "about:blank":
                active_page = page
    else:
        return None

    # Take screenshot
    try:
        screenshot = await active_page.screenshot(
            type='jpeg',
            quality=75,
            scale="css"
        )
        encoded = base64.b64encode(screenshot).decode('utf-8')
        return encoded
    except Exception as e:
        return None