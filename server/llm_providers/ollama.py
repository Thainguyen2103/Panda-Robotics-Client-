"""Small Ollama REST adapter with the same interface as the Gemini adapter."""

import json

import requests


class OllamaTextClient:
    def __init__(
        self,
        model: str,
        host: str = "http://127.0.0.1:11434",
        session=None,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.session = session or requests.Session()

    def available_models(self) -> list[str]:
        response = self.session.get(f"{self.host}/api/tags", timeout=(2, 5))
        try:
            response.raise_for_status()
            payload = response.json()
            return [
                str(item.get("model") or item.get("name") or "")
                for item in payload.get("models", [])
                if item.get("model") or item.get("name")
            ]
        finally:
            response.close()

    def ensure_ready(self) -> None:
        models = self.available_models()
        aliases = {name for name in models}
        aliases.update(name.removesuffix(":latest") for name in models)
        if self.model not in aliases:
            installed = ", ".join(models) or "không có model nào"
            raise RuntimeError(
                f"Chưa có model Ollama {self.model!r}; model hiện có: {installed}"
            )

    @staticmethod
    def _messages(messages):
        result = []
        for message in messages:
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            role = message.get("role")
            if role not in {"system", "user", "assistant"}:
                role = "user"
            result.append({"role": role, "content": content})
        return result

    def stream_chat(self, messages, max_tokens=512, temperature=.7):
        response = self.session.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": self._messages(messages),
                "stream": True,
                "think": False,
                "keep_alive": "10m",
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
            stream=True,
            timeout=(3, 120),
        )
        try:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8")
                else:
                    line = str(raw_line)
                payload = json.loads(line)
                if payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                text = (payload.get("message") or {}).get("content")
                if text:
                    yield text
        finally:
            response.close()

    def complete(self, prompt, max_tokens=200, temperature=.2):
        return "".join(self.stream_chat(
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )).strip()
