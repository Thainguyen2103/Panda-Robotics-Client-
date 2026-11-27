"""LLM cho Moon qua API mien phi, thay cho qwen3.5:2b chay local (yeu + cham).

Thu tu thu (het quota / qua tai / mat mang o cai truoc thi tu sang cai sau):
  1. Gemini Flash-Lite — 3 model khac nhau. Ban mien phi gioi han so lan goi THEO TUNG MODEL,
     nen xoay vong 3 model = gap ~3 lan so cau hoi moi ngay. Ban Flash thuong manh hon nhung
     do 2026-11 hay bao 503 (qua tai) va cho 7-25 giay -> khong dung cho robot noi chuyen.
  2. Groq (neu co groq-key.txt) — mien phi, rat nhanh.
  3. Ollama local cua Ngoc Anh (neu dang bat) — mat mang van tra loi duoc.

Khong sua code cua nhom: chi tao "client" co cung 2 ham stream_chat()/complete() nhu
server/llm_providers/gemini.py roi gan vao server.llm.engine, nen moi xu ly cua Ngoc Anh
(RAG bai hoc, dong vai, sua loi ngu phap, kiem tra ngon ngu...) van chay nguyen ban.
"""
import time

GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"]
COOLDOWN_BUSY = 60   # het quota (429) / qua tai (503): nghi model do 60 giay roi moi thu lai
COOLDOWN_ERROR = 15  # loi khac (mat mang...): nghi ngan hon


class GroqTextClient:
    """Boc Groq (kieu OpenAI) cho giong adapter Gemini cua nhom."""

    def __init__(self, api_key, model):
        from groq import Groq
        self.client, self.model = Groq(api_key=api_key, timeout=20), model

    def stream_chat(self, messages, max_tokens=512, temperature=.7):
        r = self.client.chat.completions.create(model=self.model, messages=messages,
                                                max_tokens=max_tokens, temperature=temperature)
        yield r.choices[0].message.content or ""


class FallbackClient:
    def __init__(self, providers):
        self.providers = providers            # [(ten, client), ...] theo thu tu uu tien
        self.resting = {}                     # ten -> thoi diem duoc thu lai
        self.last = None                      # ten provider vua tra loi (de in ra man hinh)

    @property
    def label(self):
        return " > ".join(name for name, _ in self.providers)

    def stream_chat(self, messages, max_tokens=512, temperature=.7):
        # Gom tron cau roi moi tra ra: neu provider dang tra loi giua chung thi loi, ta
        # chuyen sang provider khac ma khong bi noi nua cau cu + nguyen cau moi.
        # (engine cua nhom cung gom het cau truoc khi doc, nen khong cham hon.)
        errors = []
        for name, client in self.providers:
            if time.time() < self.resting.get(name, 0):
                continue
            t0 = time.time()
            try:
                text = "".join(client.stream_chat(messages, max_tokens=max_tokens,
                                                  temperature=temperature)).strip()
            except Exception as e:
                msg = str(e)
                busy = any(code in msg for code in ("429", "503", "RESOURCE_EXHAUSTED", "Too Many",
                                                     "rate limit", "quota", "Unavailable"))
                self.resting[name] = time.time() + (COOLDOWN_BUSY if busy else COOLDOWN_ERROR)
                print(f"[LLM] {name} loi ({'het quota/qua tai' if busy else msg[:80]}) -> thu cai tiep theo")
                errors.append(f"{name}: {msg[:60]}")
                continue
            if text:
                self.last = name
                print(f"[LLM] {name} tra loi sau {time.time() - t0:.1f}s")
                yield text
                return
            errors.append(f"{name}: tra ve rong")
        raise RuntimeError("Khong LLM nao tra loi duoc: " + " | ".join(errors or ["tat ca dang nghi"]))

    def complete(self, prompt, max_tokens=200, temperature=.2):
        return "".join(self.stream_chat([{"role": "user", "content": prompt}],
                                        max_tokens=max_tokens, temperature=temperature)).strip()


def build(gemini_key, groq_key=None, groq_model=None, ollama=None):
    """ollama = (model, host) neu Ollama dang chay, None neu khong."""
    from server.llm_providers.gemini import GeminiTextClient
    providers = [(m, GeminiTextClient(gemini_key, m)) for m in GEMINI_MODELS] if gemini_key else []
    if groq_key:
        try:
            providers.append((f"groq/{groq_model}", GroqTextClient(groq_key, groq_model)))
        except ImportError:
            print("[LLM] thieu thu vien groq (pip install groq) -> bo qua Groq")
    if ollama:
        from server.llm_providers.ollama import OllamaTextClient
        providers.append((f"ollama/{ollama[0]}", OllamaTextClient(*ollama)))
    return FallbackClient(providers)


# Prompt cua nhom ghi ro "Toi uu cho model nho 2B-3B": cam noi ngoai bai hoc ("Moon chua co
# bai nay...") de qwen 2b khoi bia. Model API manh hon nhieu -> noi long cho tro chuyen, ke
# chuyen, giai thich, nhung GIU luat quan trong nhat: tu vung/Kanji phai lay dung bai hoc.
STRONG_PROMPT = """You are Moon, a cheerful panda robot friend and language tutor for young children (about 4-10 years old).
Your words are spoken aloud by a speaker, so:
- Reply in the child's language (Vietnamese, English or Japanese). Never Chinese.
- Keep it short: usually 1-3 short spoken sentences; a story may be up to 6 short sentences.
- Plain spoken text only: no Markdown, lists, emoji, brackets or labels.
You can chat, play, tell short stories, tell jokes, ask questions back and explain simple things about the world, always kind and age-appropriate.
Teaching English and Japanese vocabulary is your main job:
- A system message may contain [LESSON DATA] (verified lesson). If it matches what the child asks, use its [vi]/[ja]/[en] words EXACTLY (never change Kanji, Kana, Romaji or English).
- If the lesson data is unrelated to the question, ignore it completely. Never read the lesson data or its labels out loud.
- For words not in any lesson, only teach very common words you are certain about; otherwise say you will learn it later.
When a child practises English/Japanese with mistakes: praise first, give the correct sentence to repeat, then one short simple explanation in Vietnamese.
Input comes from speech recognition: silently fix small recognition mistakes.
Never ask for personal information (full name, address, school, phone). If something sounds unsafe or sad, respond gently and suggest telling a parent or teacher."""


def add_context(engine, provider):
    """Moi lan engine dung prompt, chen them 1 doan ngu canh (vd "camera dang thay...") ngay
    truoc cau hoi cua be. provider() tra ve chuoi, hoac "" neu khong co gi. Dung cho ca
    Gemini lan Ollama (khong phu thuoc install())."""
    original = getattr(engine, "_moon_original_get_messages", engine._get_messages)
    engine._moon_original_get_messages = original

    def _get_messages(user_question, intent_decision=None):
        messages = original(user_question, intent_decision)
        extra = provider()
        if extra:
            messages.insert(len(messages) - 1, {"role": "system", "content": extra})
        return messages

    engine._get_messages = _get_messages


def install(engine, client):
    """Gan client vao engine cua Ngoc Anh. Dat ten "gemini" de engine goi stream_chat()
    (nhanh "gemini"/"ollama" trong engine._stream_provider) va dung 512 token."""
    engine._client, engine._provider_name, engine._model_name = client, "gemini", client.label
    engine._is_deepseek = False
    # engine doc 2 bien nay moi lan hoi (khong phai luc import) nen gan lai la co tac dung.
    engine.SYSTEM_PROMPT = STRONG_PROMPT
    engine.MAX_HISTORY = 8  # nho 8 luot gan nhat (model nho chi chiu duoc 3)
