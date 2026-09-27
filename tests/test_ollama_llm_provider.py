import json
import unittest

from server.llm_providers.ollama import OllamaTextClient


class _Response:
    def __init__(self, payload=None, lines=None):
        self.payload = payload
        self.lines = lines or []
        self.closed = False

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=False):
        self.decode_unicode = decode_unicode
        for line in self.lines:
            yield json.dumps(line, ensure_ascii=False).encode("utf-8")

    def close(self):
        self.closed = True


class _Session:
    def __init__(self):
        self.get_response = _Response({
            "models": [{"name": "qwen3.5:2b-q4_K_M"}],
        })
        self.post_response = _Response(lines=[
            {"message": {"role": "assistant", "content": "こん"}, "done": False},
            {"message": {"role": "assistant", "content": "にちは"}, "done": True},
        ])
        self.post_request = None

    def get(self, url, **kwargs):
        self.get_request = (url, kwargs)
        return self.get_response

    def post(self, url, **kwargs):
        self.post_request = (url, kwargs)
        return self.post_response


class OllamaTextClientTests(unittest.TestCase):
    def test_checks_installed_models(self):
        session = _Session()
        client = OllamaTextClient("qwen3.5:2b-q4_K_M", session=session)
        client.ensure_ready()
        self.assertTrue(session.get_request[0].endswith("/api/tags"))
        self.assertTrue(session.get_response.closed)

    def test_missing_model_has_actionable_error(self):
        client = OllamaTextClient("moon-tutor", session=_Session())
        with self.assertRaisesRegex(RuntimeError, "qwen3.5:2b-q4_K_M"):
            client.ensure_ready()

    def test_stream_chat_uses_native_chat_api_and_utf8(self):
        session = _Session()
        client = OllamaTextClient("qwen3.5:2b-q4_K_M", session=session)
        result = "".join(client.stream_chat([
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "こんにちは"},
        ], max_tokens=123, temperature=.4))

        self.assertEqual(result, "こんにちは")
        url, request = session.post_request
        self.assertTrue(url.endswith("/api/chat"))
        self.assertEqual(request["json"]["model"], "qwen3.5:2b-q4_K_M")
        self.assertEqual(request["json"]["options"]["num_predict"], 123)
        self.assertEqual(request["json"]["options"]["temperature"], .4)
        self.assertFalse(request["json"]["think"])
        self.assertFalse(session.post_response.decode_unicode)
        self.assertTrue(session.post_response.closed)


if __name__ == "__main__":
    unittest.main()
