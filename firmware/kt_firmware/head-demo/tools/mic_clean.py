"""Lam sach tieng mic robot (INMP441) truoc khi gui Gemini — chi can numpy, khong cai them gi.

Do tren file ghi that (debug_mic_last.wav, 30/10): giong noi to hon tieng on nen ~24 lan, tuc
mic va phong KHONG on. Tieng "re" la do firmware cu dich >>14: noi to/sat mic thi so vuot int16
roi "quan" sang dau nguoc -> lop bop, Gemini chep sai. Firmware moi dich >>16 nen het tran;
file nay lo phan con lai:
  - voice_level / is_voice: biet khung nao co tieng noi de dung ghi dung luc (truoc day lech
    DC ~660 luon vuot nguong 350 -> lan nao cung ghi du 8 giay, ke ca 6 giay im lang)
  - clean: bo tieng u tram, cat im lang dau/cuoi, chinh am luong ve 1 muc
"""
import wave

import numpy as np

SAMPLE_RATE = 16000

# Bo 0,25 giay dau moi lan ghi: file ghi that co 1 tieng "cop" o 0,03-0,2 s dau (nhieu kha
# nang la tieng go phim SPACE lot vao mic, cong ~0,1 s tieng cu con trong bo dem I2S cua board).
SKIP_START_SEC = 0.25
# Khung "co tieng noi" = to hon tieng on nen cua phong VOICE_OVER_NOISE lan (do lai moi lan ghi
# nen phong yen hay on deu dung duoc) VA khong nho hon MIN_VOICE_LEVEL. Do that: phong yen ~10,
# noi gan mic ~200. Noi xa ma AI khong nghe thay -> GIAM MIN_VOICE_LEVEL; cho on qua ma AI ghi
# mai khong chiu dung -> TANG VOICE_OVER_NOISE.
VOICE_OVER_NOISE = 3.0
MIN_VOICE_LEVEL = 40
TARGET_PEAK = 20000  # dinh tieng noi sau khi chinh ~60% muc toi da cua int16
MAX_GAIN = 10.0      # to len toi da x10: noi xa van duoc bu, nhung khong thoi phong ca tieng on


def voice_level(samples):
    """Muc "co tieng noi" cua 1 khung = trung binh do chenh giua 2 mau lien nhau.
    Giong noi doi nhanh (hang tram -> vai nghin Hz) nen chenh lon; lech DC va tieng u tram (hoi
    tho phả vao mic, rung ban) doi rat cham nen gan nhu khong duoc tinh -> khong can bo loc."""
    s = np.asarray(samples, dtype=np.int32)
    return float(np.abs(np.diff(s)).mean()) if len(s) > 1 else 0.0


def voice_threshold(levels):
    """Nguong tu chinh theo phong: 15% khung yen nhat tu dau lan ghi = tieng on nen."""
    return max(MIN_VOICE_LEVEL, float(np.percentile(levels, 15)) * VOICE_OVER_NOISE)


def is_voice(levels):
    """Khung moi nhat co phai tieng noi khong. Lay trung vi 5 khung gan nhat (80 ms) de 1 tieng
    "tach" ngan (day long, cham tay vao mach) khong bi tinh la dang noi."""
    return float(np.median(levels[-5:])) > voice_threshold(levels)


def count_wraps(pcm):
    """So lan 2 mau lien nhau chenh > 40000: chi xay ra khi so bi tran int16 roi quan dau
    (firmware cu >>14) — giong noi that o 16 kHz khong bao gio nhay xa nhu vay."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.int32)
    return int((np.abs(np.diff(x)) > 40000).sum())


def clean(pcm, start_sec, end_sec):
    """Tra ve (pcm da lam sach, he so khuech dai). Chi giu doan start_sec..end_sec, them 0,3 s
    moi dau: Gemini can 1 chut lang truoc tieng noi moi nhan ra cau bat dau tu dau."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    # 1. Bo tieng u tram: duoi 50 Hz bo han, 50-100 Hz giam dan (doc tron — cat dung 1 nhat se
    #    sinh tieng vang). Giong nguoi khong can phan nay. Lam bang FFT: doi sang mien tan so,
    #    nhan he so, doi nguoc. Dem them 0,1 s so 0 vi FFT coi tin hieu la vong tron: khong dem
    #    thi tieng cuoi file "tran" sang dau file.
    n = len(x) + SAMPLE_RATE // 10
    spec = np.fft.rfft(x - x.mean(), n)
    freqs = np.fft.rfftfreq(n, 1 / SAMPLE_RATE)
    spec *= 0.5 - 0.5 * np.cos(np.pi * np.clip((freqs - 50) / 50, 0, 1))
    x = np.fft.irfft(spec, n)[:len(x)]
    # 2. Cat im lang dau/cuoi: nghe vai giay tieng on nen la luc Gemini hay "doan" bua ra chu.
    x = x[max(0, int((start_sec - 0.3) * SAMPLE_RATE)):int((end_sec + 0.3) * SAMPLE_RATE)]
    # 3. Chinh am luong ve 1 muc. Lay muc 99,9% thay vi mau to nhat de 1 tieng tach le khong
    #    lam ca cau bi chinh nho di.
    peak = float(np.percentile(np.abs(x), 99.9)) if len(x) else 0.0
    gain = min(TARGET_PEAK / peak, MAX_GAIN) if peak > 0 else 1.0
    return np.clip(x * gain, -32767, 32767).astype(np.int16).tobytes(), gain


def save_wav(path, pcm):
    """Luu de TU NGHE THU bang Windows Media Player/VLC (ghi de file cu, khong giu lich su)."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
