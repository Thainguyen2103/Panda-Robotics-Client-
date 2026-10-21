# Copy to config/secrets.py and fill locally. Never commit real credentials.
SECRETS = {
    "GEMINI_API_KEY": "",       # Gemini Live and transcription
    "GROQ_API_KEY": "",         # Optional Whisper/STT fallback
    "FISH_AUDIO_API_KEY": "",   # Optional Fish voice
    "DEEPSEEK_API_KEY": "",     # Optional LLM fallback
    "PICOVOICE_ACCESS_KEY": "", # Optional acoustic wakeword
}
