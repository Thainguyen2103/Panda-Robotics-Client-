"""Reusable PCM measurements and transformations."""
import io
import time
import wave


def rms_of_block(data: bytes, np_module) -> float:
    arr = np_module.frombuffer(data, dtype=np_module.int16).astype(np_module.float32) / 32768.0
    if arr.size == 0:
        return 0.0
    return float(np_module.sqrt(np_module.mean(arr ** 2)))


def spectral_flatness(data: bytes, np_module) -> float:
    arr = np_module.frombuffer(data, dtype=np_module.int16).astype(np_module.float32) / 32768.0
    if arr.size == 0:
        return 1.0
    spec = np_module.abs(np_module.fft.rfft(arr * np_module.hanning(arr.size))) ** 2
    spec = spec[1:]
    mean = float(np_module.mean(spec))
    if mean <= 1e-12:
        return 1.0
    geo = float(np_module.exp(np_module.mean(np_module.log(spec + 1e-12))))
    return min(1.0, geo / mean)


def denoise_pcm(audio: bytes, *, np_module, reducer, enabled: bool, sample_rate: int) -> bytes:
    if not reducer or not enabled or np_module is None:
        return audio
    try:
        arr = np_module.frombuffer(audio, dtype=np_module.int16).astype(np_module.float32) / 32768.0
        block_size = 480
        if len(arr) >= block_size:
            blocks = arr[:(len(arr) // block_size) * block_size].reshape(-1, block_size)
            peak = float(np_module.max(np_module.sqrt(np_module.mean(blocks ** 2, axis=1))))
            if peak >= 0.3:
                return audio
        started = time.time()
        clean = reducer.reduce_noise(y=arr, sr=sample_rate, stationary=True)
        print(f"🧹 [VOICE] denoise {time.time() - started:.2f}s (giọng yếu)")
        return (np_module.clip(clean, -1.0, 1.0) * 32767.0).astype(np_module.int16).tobytes()
    except Exception:
        return audio


def wrap_wav(audio: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(audio)
    return buffer.getvalue()
