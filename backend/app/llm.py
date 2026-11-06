"""Groq chat-completions client (server side only; the key never reaches the browser)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

SYSTEM = (
    "You are the ArthSetu assistant: an educational helper for a credit-risk decision-support platform. "
    "Rules: answer ONLY from the CONTEXT passages for anything about the ArthSetu model, data, metrics or platform; if the "
    "context does not contain it, say you don't have that information. Never invent metrics. You do not make lending decisions, "
    "do not approve or reject anyone, and do not give personalised financial advice; for those, suggest a qualified professional. "
    "Explain explanations as model contributions, not causes. Keep answers short and clear. Reply in the language requested "
    "(English or Hindi; keep key English finance terms in brackets in Hindi)."
)


class LLMError(Exception):
    pass


def call_groq(messages: list[dict], api_key: str, model: str, url: str, timeout: float = 25.0) -> str:
    if not api_key or not model:
        raise LLMError("not_configured")
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 450}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                                          "User-Agent": "arthsetu/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        raise LLMError(f"http_{e.code}") from None      # never echo upstream bodies (may contain details)
    except Exception as e:
        raise LLMError(type(e).__name__) from None
