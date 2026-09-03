# tools/bench_topics.py — benchmark độ chính xác phân loại chủ đề hybrid
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from server import brain
from server.topics import classify_topic

CASES = [
    ("Tích phân là gì?", "math"),
    ("Hôm nay trời có mưa không?", "weather"),
    ("Bây giờ là mấy giờ?", "time"),
    ("Ronaldo là ai?", "people"),
    ("Con mèo nhà bạn tên gì?", "animal"),
    ("Một đô la bằng bao nhiêu tiền Việt?", "money"),
    ("Phim Conan có bao nhiêu tập?", "movie"),
    ("Mặt trăng cách trái đất bao xa?", "space"),
    ("Đau bụng nên làm gì?", "health"),
    ("Chiến tranh thế giới thứ hai kết thúc năm nào?", "history"),
    ("Thủ đô của Úc là gì?", "geography"),
    ("Hơi tiếc hôn ngang như thế nào?", "weather"),   # nhiễu ASR của 'thời tiết hôm nay'
    ("Kể chuyện cười đi", "story"),
    ("Máy tính lượng tử hoạt động ra sao?", "tech|science"),
    ("Buồn quá Panda ơi", "emotion"),
]

ok = 0
for q, expect in CASES:
    kw = classify_topic(q)
    tid, _ = brain._correct_and_classify(q)
    got = kw if kw != "chat" else (tid or "chat")
    good = got in expect.split("|")
    ok += good
    print(f"{'✅' if good else '❌'} {got:10} (mong đợi {expect:14}) <- {q}")

print(f"\nKẾT QUẢ: {ok}/{len(CASES)} chính xác ({ok/len(CASES)*100:.0f}%)")
