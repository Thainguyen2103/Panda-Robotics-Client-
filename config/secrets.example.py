# config/secrets.example.py — BẢN MẪU, an toàn để push lên Git
# Cách dùng: copy file này thành config/secrets.py rồi điền key thật của bạn.
# File secrets.py thật đã nằm trong .gitignore — KHÔNG BAO GIỜ push.
SECRETS = {
    "FISH_AUDIO_API_KEY": "",   # TTS — lấy tại https://fish.audio
    "GROQ_API_KEY": "",         # STT + LLM — lấy tại https://console.groq.com
    "DEEPSEEK_API_KEY": "",     # tuỳ chọn (fallback LLM)
}
