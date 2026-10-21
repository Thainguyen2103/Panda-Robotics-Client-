# Voice/Vision integration — 21/10/2026

Branch: `feature/thai-refactor-voice-vision`.
Integrated team baseline: `origin/develop` at `954ac2d` (PR #11).
The pre-integration Vision work and three existing Word reports were saved in
`9c65367`. The reports retain their original contents and dates.

## Changes

- Preserve the emotion improvements, evaluation utility and dashboard labels.
- Keep the team's LLM/RAG v2, Edge TTS, network module layout and `moon/` topics.
- Restore the browser Voice VAD/session settings still required by its runtime.
- Prefer `.voice-venv` for browser Voice, with `server/venv` as a fallback.
- Select Vision compute automatically; `MOON_VISION_DEVICE` can override it.
- Exclude English function words from the Jaccard fallback so ordinary chat
  does not retrieve unrelated lessons when sentence-transformers is unavailable.
- Update MQTT test fixtures and the topic benchmark import to the new layout.
- Update the face-coordinate test for the team's full-frame detector behavior.
- Restore an empty credentials template and ignore `.codex-temp/` outputs.

## Verification

- 187 Python unit tests across 20 test files passed in separate processes.
  Vision/LLM tests used `server/venv`; `test_voice_session.py` used
  `.voice-venv` (Python 3.12 with WebRTC VAD).
- All 11 `tests/test_*.cjs` suites passed, including dashboard transport,
  continuous Voice, fake-microphone browser flow, OLED states and Vision UI.
- `tools/check_vision.py --frames 2` passed with all seven model branches loaded
  and an empty errors object, using blank frames without opening a camera.
- `git diff --check` passed.

Run each Python test file in its own process to avoid module-mock interactions.
For example:

```powershell
.\server\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_vision*.py'
.\.voice-venv\Scripts\python.exe -m unittest discover -s tests -p 'test_voice_session.py'
node tests/test_vision_ui.cjs
```

The browser tests require Playwright and Edge plus a dashboard on localhost:3000.
Voice transport tests require its service on localhost:8765 and a configured
Groq key; the silence-only transport checks do not submit speech to STT.

## Limits

Ollama was not running during verification. Real conversation with the LLM,
online TTS quality, hardware behavior and camera emotion accuracy were not
verified. The current main Python environment lacks sentence-transformers;
the lexical/Jaccard fallback is covered, and vector regression tests use
fixtures. Model loading on blank frames does not establish camera accuracy.

The interactive/service diagnostics `test_e2e_auto.py`, `test_pipeline.py` and
`test_ram.py` were excluded from the unit-test count.
