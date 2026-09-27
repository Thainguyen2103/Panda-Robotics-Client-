"""Small Gemini REST adapter with streaming text output."""
import json

import requests


class GeminiTextClient:
    def __init__(self, api_key, model="gemini-3.5-flash-lite", session=None):
        self.api_key = api_key
        self.model = model
        self.session = session or requests.Session()

    @staticmethod
    def _request_body(messages, max_tokens, temperature):
        system = []
        contents = []
        for message in messages:
            text = str(message.get("content") or "").strip()
            if not text:
                continue
            role = message.get("role")
            if role == "system":
                system.append(text)
                continue
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            })
        body = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        return body

    def stream_chat(self, messages, max_tokens=512, temperature=.7):
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:streamGenerateContent"
        )
        response = self.session.post(
            url,
            params={"alt": "sse"},
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=self._request_body(messages, max_tokens, temperature),
            stream=True,
            timeout=(8, 45),
        )
        try:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=False):
                if isinstance(raw_line, bytes):
                    line = raw_line.decode("utf-8").strip()
                else:
                    line = str(raw_line or "").strip()
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                if payload.get("error"):
                    raise RuntimeError(payload["error"].get("message", "Gemini API error"))
                candidates = payload.get("candidates") or []
                if not candidates:
                    continue
                for part in candidates[0].get("content", {}).get("parts", []):
                    text = part.get("text")
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
