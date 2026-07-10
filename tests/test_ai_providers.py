"""The AI provider registry: the panel's contract with its back-ends."""
from khervepdf import ai_providers as p


def test_required_providers_present():
    # The panel promises OpenAI, Claude, Ollama and Mistral (plus the
    # family's Local server entry).
    for name in ("ChatGPT", "Claude", "Ollama", "Mistral", "Local"):
        assert name in p.PROVIDERS
        assert name in p.DISPLAY_NAMES
        assert name in p.DEFAULT_BASE
        assert name in p.PROVIDER_HELP


def test_key_requirements():
    assert p.NEEDS_KEY == {"Claude", "ChatGPT", "Mistral"}
    assert "Ollama" not in p.NEEDS_KEY  # local — must work keyless


def test_base_url_override_and_default():
    assert p._base("Ollama") == "http://localhost:11434"
    assert p._base("Claude", "https://proxy.example.com/") == \
        "https://proxy.example.com"


def test_image_attachment_formats():
    msgs = [{"role": "user", "content": "what is this?"}]
    claude = p._with_image(msgs, "AAAA", "Claude")
    assert claude[0]["content"][1]["source"]["data"] == "AAAA"
    ollama = p._with_image(msgs, "AAAA", "Ollama")
    assert ollama[0]["images"] == ["AAAA"]
    openai = p._with_image(msgs, "AAAA", "ChatGPT")
    assert openai[0]["content"][1]["image_url"]["url"].endswith("AAAA")
    # The original message list is never mutated.
    assert msgs[0]["content"] == "what is this?"
