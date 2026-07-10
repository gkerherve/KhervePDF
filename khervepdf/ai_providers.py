"""AI provider registry — chat + model listing over plain urllib.

Mirrors KhervePaint's ai_providers module (the Kherve-family AI panel
convention). Five back-ends share one interface so the assistant panel
can switch freely and a single Refresh button can list each one's
models:

* **Claude** (Anthropic Messages API)
* **ChatGPT** (OpenAI), **Mistral**, and **Local** — OpenAI-compatible
* **Ollama** (local, no key)

Only the standard library is used (urllib + json), so there are no new
dependencies. Network calls are blocking; callers run them off the UI
thread (see ai_panel.py).
"""

import json
import urllib.error
import urllib.request

ANTHROPIC_VERSION = "2023-06-01"

#: provider -> default base URL.
DEFAULT_BASE = {
    "Claude": "https://api.anthropic.com",
    "ChatGPT": "https://api.openai.com",
    "Mistral": "https://api.mistral.ai",
    "Ollama": "http://localhost:11434",
    "Local": "http://localhost:1234",
}

#: providers that require an API key.
NEEDS_KEY = {"Claude", "ChatGPT", "Mistral"}

#: OpenAI-compatible chat/models providers.
_OPENAI_LIKE = {"ChatGPT", "Mistral", "Local"}

PROVIDERS = list(DEFAULT_BASE)

#: Friendly names shown in the settings dialog.
DISPLAY_NAMES = {
    "Claude": "Anthropic (Claude)",
    "ChatGPT": "OpenAI (ChatGPT)",
    "Mistral": "Mistral",
    "Ollama": "Ollama (local)",
    "Local": "Local server",
}

#: "How to get an API key" guidance per provider.
PROVIDER_HELP = {
    "Claude": ("To get an API key:\n"
               "1. Go to console.anthropic.com\n"
               "2. Sign up or log in\n"
               "3. Navigate to API Keys in the left sidebar\n"
               "4. Click \"Create Key\" and copy the key (starts with sk-ant-)\n"
               "5. Add credit to your account under Billing"),
    "ChatGPT": ("To get an API key:\n"
                "1. Go to platform.openai.com\n"
                "2. Sign up or log in\n"
                "3. Open API keys (top-right account menu)\n"
                "4. Click \"Create new secret key\" and copy it (sk-...)\n"
                "5. Add a payment method under Billing"),
    "Mistral": ("To get an API key:\n"
                "1. Go to console.mistral.ai\n"
                "2. Sign up or log in\n"
                "3. Open API Keys\n"
                "4. Create a new key and copy it\n"
                "5. Add billing if required"),
    "Ollama": ("No API key needed — Ollama runs locally:\n"
               "1. Install Ollama from ollama.com\n"
               "2. Start it (serves at http://localhost:11434)\n"
               "3. Pull a model, e.g.  ollama pull llama3\n"
               "4. Click the refresh icon to list installed models"),
    "Local": ("For a local OpenAI-compatible server "
              "(LM Studio, llama.cpp, vLLM…):\n"
              "1. Start the server\n"
              "2. Set the Base URL (e.g. http://localhost:1234)\n"
              "3. An API key is usually not required\n"
              "4. Click the refresh icon to list models"),
}

#: Built-in model lists so the combo is useful before you Refresh.
#: The Refresh button pulls the provider's live list (the source of truth).
DEFAULT_MODELS = {
    "Claude": ["claude-opus-4-8", "claude-sonnet-5",
               "claude-haiku-4-5-20251001", "claude-fable-5"],
    "ChatGPT": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini",
                "o3", "o4-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "Mistral": ["mistral-large-latest", "mistral-medium-latest",
                "mistral-small-latest", "open-mistral-nemo",
                "codestral-latest"],
    "Ollama": ["llama3.2", "llama3.1", "llama3", "mistral", "qwen2.5",
               "gemma2", "phi3"],
    "Local": [],
}


def _base(provider, base_url=""):
    return (base_url or DEFAULT_BASE[provider]).rstrip("/")


def _send(req, timeout):
    """Run a request, turning an HTTP error into the API's own message."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        try:
            data = json.loads(detail)
            detail = (data.get("error", {}).get("message")
                      or data.get("message") or detail)
        except ValueError:
            pass
        hint = ""
        if err.code in (401, 403):
            hint = " — check your API key in Settings (no spaces/newlines)."
        raise RuntimeError(f"HTTP {err.code}: {detail[:300]}{hint}")


def _post(url, body, headers, timeout=90):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    return _send(req, timeout)


def _get(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers, method="GET")
    return _send(req, timeout)


def _with_image(messages, image_b64, provider):
    """Attach a base64 PNG to the last user message, in *provider*'s
    multimodal format (so a pasted screenshot reaches a vision model)."""
    msgs = [dict(m) for m in messages]
    idx = next((i for i in range(len(msgs) - 1, -1, -1)
                if msgs[i].get("role") == "user"), None)
    if idx is None:
        return msgs
    text = msgs[idx].get("content", "")
    if provider == "Claude":
        msgs[idx]["content"] = [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "base64",
             "media_type": "image/png", "data": image_b64}}]
    elif provider == "Ollama":
        msgs[idx] = {"role": "user", "content": text, "images": [image_b64]}
    else:                                       # OpenAI-compatible
        msgs[idx]["content"] = [
            {"type": "text", "text": text},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{image_b64}"}}]
    return msgs


def chat(provider, model, messages, api_key="", base_url="", image=None):
    """Send *messages* ([{role, content}, …]) and return the reply text.
    *image* (base64 PNG) is attached to the last user message if given."""
    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip()
    if image:
        messages = _with_image(messages, image, provider)
    if provider in _OPENAI_LIKE:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = _post(f"{_base(provider, base_url)}/v1/chat/completions",
                     {"model": model, "messages": messages}, headers)
        return data["choices"][0]["message"]["content"]

    if provider == "Claude":
        system = "\n\n".join(m["content"] for m in messages
                             if m["role"] == "system")
        convo = [m for m in messages if m["role"] != "system"]
        body = {"model": model, "max_tokens": 4096, "messages": convo}
        if system:
            body["system"] = system
        data = _post(f"{_base('Claude', base_url)}/v1/messages", body,
                     {"x-api-key": api_key,
                      "anthropic-version": ANTHROPIC_VERSION})
        return "".join(b.get("text", "") for b in data.get("content", [])
                       if b.get("type") == "text")

    if provider == "Ollama":
        data = _post(f"{_base('Ollama', base_url)}/api/chat",
                     {"model": model, "messages": messages, "stream": False},
                     {})
        return data["message"]["content"]

    raise ValueError(f"unknown provider: {provider}")


def list_models(provider, api_key="", base_url=""):
    """Return the available model ids for *provider* (sorted)."""
    api_key = (api_key or "").strip()
    base_url = (base_url or "").strip()
    if provider in _OPENAI_LIKE:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        data = _get(f"{_base(provider, base_url)}/v1/models", headers)
        return sorted(m["id"] for m in data.get("data", []) if m.get("id"))

    if provider == "Claude":
        data = _get(f"{_base('Claude', base_url)}/v1/models",
                    {"x-api-key": api_key,
                     "anthropic-version": ANTHROPIC_VERSION})
        return sorted(m["id"] for m in data.get("data", []) if m.get("id"))

    if provider == "Ollama":
        data = _get(f"{_base('Ollama', base_url)}/api/tags", {})
        return sorted(m["name"] for m in data.get("models", []))

    raise ValueError(f"unknown provider: {provider}")
