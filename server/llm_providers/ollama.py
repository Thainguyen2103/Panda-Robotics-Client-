"""Small Ollama REST adapter with the same interface as the Gemini adapter.

Tối ưu hóa cho RTX 4050:
- num_gpu=99: Offload 100% layers vào VRAM (RTX 4050 có 6GB, Qwen 2B ~1.5GB FP16)
- num_ctx=2048: Context window đủ cho RAG prompt + history mà không phí VRAM
- num_batch=256: Batch size lớn hơn cho prompt processing nhanh hơn trên GPU
- mmap=True: Memory-mapped model loading, giảm startup time
- keep_alive=30m: Giữ model trong VRAM 30 phút, tránh reload khi bé hỏi liên tục
- f16_kv=True: KV cache dùng FP16 thay FP32, tiết kiệm 50% VRAM cho cache
"""

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

        # ── Pre-load model vào VRAM để câu hỏi đầu tiên không bị lag ────────
        try:
            self.session.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": "",
                    "keep_alive": "30m",
                    "options": {"num_gpu": 99},
                },
                timeout=(5, 30),
            ).close()
            print(f"🚀 [Ollama] Pre-loaded {self.model} vào VRAM (keep_alive=30m)")
        except Exception as e:
            print(f"⚠️ [Ollama] Pre-load warning: {e}")

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
                "keep_alive": "30m",
                "options": {
                    # ── GPU Offloading ────────────────────────────────
                    "num_gpu": 99,          # Offload TẤT CẢ layers vào GPU
                    # ── Context & Generation ─────────────────────────
                    "num_ctx": 2048,        # Context window (RAG + history + system)
                    "num_predict": max_tokens,
                    "num_batch": 256,       # Prompt eval batch size (GPU nhanh hơn)
                    # ── Sampling ─────────────────────────────────────
                    "temperature": temperature,
                    "top_p": 0.85,          # Nucleus sampling
                    "top_k": 30,            # Giới hạn token candidates
                    "repeat_penalty": 1.15, # Chống lặp từ
                    # ── Performance ──────────────────────────────────
                    "f16_kv": True,         # KV cache FP16 → tiết kiệm 50% VRAM
                    "mmap": True,           # Memory-mapped loading
                    "num_thread": 4,        # CPU threads cho phần không GPU
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
