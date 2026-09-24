"""Provider adapters. API credentials stay in this process, outside chat/history."""

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request

from domain import REPLY_SCHEMA, ValidationError, validate_reply


PROVIDERS = {
    "chatgpt": ("ChatGPT — account sign-in", "", ""),
    "openai": ("OpenAI — API", "https://api.openai.com/v1", "https://platform.openai.com/api-keys"),
    "anthropic": ("Anthropic / Claude — API", "https://api.anthropic.com/v1", "https://platform.claude.com/settings/keys"),
    "gemini": ("Google Gemini — API", "https://generativelanguage.googleapis.com/v1beta/openai", "https://aistudio.google.com/apikey"),
    "ollama": ("Ollama — local model", "http://127.0.0.1:11434", "https://ollama.com"),
    "compatible": ("Other OpenAI-compatible API", "", ""),
}


class ProviderError(RuntimeError):
    pass


def plain_http_allowed(host):
    """Unencrypted HTTP only inside this computer or the local network, for example
    Ollama on another PC at home. Host names are refused: they could resolve anywhere."""
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward provider authorization to a redirect destination.
        return None


def parse_json_reply(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3]
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3]
    try:
        return validate_reply(json.loads(text))
    except (ValueError, TypeError) as exc:
        raise ProviderError("The model returned an incomplete reply. Send it again or pick another model.") from exc


class APIProvider:
    def __init__(self, kind, endpoint, key=""):
        if kind not in PROVIDERS or kind == "chatgpt":
            raise ProviderError("Unknown API provider")
        url = urllib.parse.urlsplit(endpoint)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ProviderError("Enter the API base URL without keys, parameters or credentials")
        if url.scheme != "https" and not (url.scheme == "http" and kind in ("ollama", "compatible")
                                           and plain_http_allowed(url.hostname)):
            raise ProviderError("A provider outside your local network needs HTTPS; "
                                "plain HTTP works only with a local-network IP address")
        if kind not in ("ollama", "compatible") and not key.strip():
            raise ProviderError("Enter your API key in the key field")
        self.kind, self.endpoint, self.key = kind, endpoint.rstrip("/"), key.strip()
        self.model = ""
        self.opener = urllib.request.build_opener(NoRedirect)

    def close(self):
        self.key = ""

    def request(self, path, body=None):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.kind == "anthropic":
            headers.update({"x-api-key": self.key, "anthropic-version": "2023-06-01"})
        elif self.key:
            headers["Authorization"] = "Bearer " + self.key
        request = urllib.request.Request(self.endpoint + path,
            data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=120) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProviderError("The provider’s response is too large")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            descriptions = {401: "Key not accepted", 403: "Access denied", 404: "API or model not found",
                            429: "Request or spending limit reached"}
            # Provider error bodies can echo credentials or user input. Do not log them.
            raise ProviderError(f"{descriptions.get(exc.code, 'Provider error')} (HTTP {exc.code})") from None
        except (OSError, ValueError, urllib.error.URLError):
            raise ProviderError("No response. Check the network and the API URL.") from None

    def models(self):
        data = self.request("/api/tags" if self.kind == "ollama" else "/models")
        if self.kind == "ollama":
            return [m["name"] for m in data.get("models", []) if isinstance(m.get("name"), str)]
        return [m["id"] for m in data.get("data", []) if isinstance(m.get("id"), str)]

    def reply(self, system, messages):
        if not self.model.strip():
            raise ProviderError("Pick a model")
        if self.kind == "openai":
            data = self.request("/responses", {"model": self.model, "store": False,
                "instructions": system, "input": messages,
                "text": {"format": {"type": "json_schema", "name": "installer_reply",
                                    "strict": True, "schema": REPLY_SCHEMA}}})
            if data.get("status") != "completed":
                raise ProviderError("The provider didn’t finish the reply; the configuration is unchanged")
            text = "".join(c.get("text", "") for item in data.get("output", [])
                           if item.get("type") == "message" for c in item.get("content", [])
                           if c.get("type") == "output_text")
        elif self.kind == "anthropic":
            data = self.request("/messages", {"model": self.model, "max_tokens": 8192,
                "system": system, "messages": messages,
                "tools": [{"name": "installer_reply", "description": "Reply to the installer user",
                           "input_schema": REPLY_SCHEMA}],
                "tool_choice": {"type": "tool", "name": "installer_reply"}})
            if data.get("stop_reason") != "tool_use":
                raise ProviderError("The model didn’t finish its structured reply")
            calls = [c for c in data.get("content", []) if c.get("type") == "tool_use"
                     and c.get("name") == "installer_reply"]
            if len(calls) != 1:
                raise ProviderError("The model’s reply was ambiguous")
            return validate_reply(calls[0].get("input"))
        elif self.kind == "ollama":
            data = self.request("/api/chat", {"model": self.model, "stream": False,
                "format": REPLY_SCHEMA, "messages": [{"role": "system", "content": system}, *messages]})
            if not data.get("done"):
                raise ProviderError("The local model didn’t finish the reply")
            text = data.get("message", {}).get("content", "")
        else:
            data = self.request("/chat/completions", {"model": self.model,
                "messages": [{"role": "system", "content": system}, *messages],
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "installer_reply", "strict": True, "schema": REPLY_SCHEMA}}})
            choices = data.get("choices", [])
            if not choices or choices[0].get("finish_reason") != "stop":
                raise ProviderError("The model didn’t finish the reply")
            text = choices[0].get("message", {}).get("content") or ""
        return parse_json_reply(text)
