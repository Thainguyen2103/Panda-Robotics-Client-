import json
import unittest

from server.llm_providers.gemini import GeminiTextClient


class _FakeResponse:
    def __init__(self):
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        assert not decode_unicode
        for text in ("こん", "にちは"):
            line = "data: " + json.dumps({
                "candidates": [{"content": {"parts": [{"text": text}]}}]
            })
            yield line.encode("utf-8")

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self):
        self.request = None
        self.response = _FakeResponse()

    def post(self, url, **kwargs):
        self.request = (url, kwargs)
        return self.response


class GeminiTextClientTests(unittest.TestCase):
    def test_stream_chat_converts_messages_and_parses_sse(self):
        session = _FakeSession()
        client = GeminiTextClient("test-key", "gemini-test", session=session)
        messages = [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "こんにちは"},
            {"role": "assistant", "content": "はい"},
        ]

        result = "".join(client.stream_chat(messages, max_tokens=123))

        self.assertEqual(result, "こんにちは")
        url, request = session.request
        self.assertTrue(url.endswith("gemini-test:streamGenerateContent"))
        self.assertEqual(request["params"], {"alt": "sse"})
        self.assertEqual(request["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(request["json"]["generationConfig"]["maxOutputTokens"], 123)
        self.assertEqual(request["json"]["systemInstruction"]["parts"][0]["text"], "Be concise.")
        self.assertEqual(request["json"]["contents"][1]["role"], "model")
        self.assertTrue(session.response.closed)


if __name__ == "__main__":
    unittest.main()
