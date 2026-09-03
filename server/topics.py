"""
Topic classifier — server/topics.py
====================================
Phân loại CHỦ ĐỀ câu hỏi bằng keyword (tức thì, không latency) để OLED
hiển thị emoji tượng trưng trong lúc Panda nghĩ & trả lời:
  hỏi giờ → 🕐 | thời tiết → 🌦️ | toán → 🧮 | cảm xúc → 💗 | ...
"""
import re

# Thứ tự quan trọng: chủ đề hẹp/đặc trưng kiểm tra trước
TOPICS = [
    ("time",     ["mấy giờ", "thời gian", "thứ mấy", "ngày nào", "ngày bao nhiêu",
                  "what time", "date today", "hôm nay là ngày"]),
    ("weather",  ["thời tiết", "mưa", "nắng", "nhiệt độ", "gió", "weather",
                  "rain", "sunny", "trời có"]),
    ("money",    ["đô la", "tiền việt", "bao nhiêu tiền", "giá", "tiền",
                  "mua", "bán", "đắt", "rẻ", "lương"]),
    ("math",     ["toán", "cộng", "trừ", "nhân với", "chia",
                  "bằng bao nhiêu", "phép tính", "math", "calculate", "plus", "minus",
                  "bằng mấy", "một cộng", "chia cho"]),
    ("story",    ["kể chuyện", "câu chuyện", "truyện", "bài thơ", "thơ",
                  "đọc thơ", "story", "poem"]),
    ("emotion",  ["buồn", "vui", "yêu", "thương", "cảm xúc", "tâm lý", "khóc",
                  "cô đơn", "giận", "mệt mỏi", "love", "sad", "feel", "happy",
                  "thất tình", "chán"]),
    ("food",     ["đói", "ăn gì", "món", "uống", "food", "eat", "cook", "ẩm thực",
                  "phở", "cơm", "bún"]),
    ("music",    ["bài hát", "hát", "nhạc", "music", "song"]),
    ("sport",    ["bóng đá", "thể thao", "đá bóng", "chạy bộ", "tập gym",
                  "cầu lông", "bơi", "sport", "football", "world cup"]),
    ("animal",   ["con gì", "động vật", "chó", "mèo", "chim", "cá", "loài",
                  "animal", "pet"]),
    ("nature",   ["núi", "sông", "biển", "cao nhất", "lớn nhất",
                  "sa mạc", "rừng"]),
    ("place",    ["ở đâu", "đường đi", "địa điểm", "thành phố",
                  "where", "du lịch"]),
    ("study",    ["văn học", "tiếng anh", "thi", "bài tập",
                  "điểm", "trường", "study", "exam"]),
    ("tech",     ["máy tính", "điện thoại", "internet", "facebook", "youtube",
                  "zalo", "ai là gì", "robot", "công nghệ", "phone", "computer"]),
    ("people",   ["là ai", "ai là", "tổng thống", "ca sĩ", "cầu thủ",
                  "người nổi tiếng", "who is"]),
    ("game",     ["game", "chơi", "cờ", "esport", "liên quân", "minecraft"]),
    ("science",  ["hóa học", "vật lý", "thí nghiệm", "nguyên tử", "phân tử",
                  "science", "phản ứng"]),
    ("history",  ["lịch sử", "chiến tranh", "triều đại", "vua", "cách mạng",
                  "history"]),
    ("geography",["thủ đô", "nước nào", "quốc gia", "châu lục", "dân số",
                  "geography", "bản đồ"]),
    ("space",    ["mặt trăng", "sao hỏa", "vũ trụ", "hành tinh", "ngôi sao",
                  "space", "thiên văn", "tên lửa"]),
    ("health",   ["đau", "bệnh", "bác sĩ", "thuốc", "sức khỏe",
                  "health"]),
    ("movie",    ["phim", "anime", "diễn viên", "đạo diễn", "movie", "cartoon"]),
    ("identity", ["tên gì", "bạn là", "bao nhiêu tuổi", "who are you",
                  "your name"]),
]

DEFAULT_TOPIC = "chat"

# Caption mặc định hiển thị dưới emoji (time/weather được brain điền dữ liệu thật)
TOPIC_LABELS = {
    "time": "TIME", "weather": "WEATHER", "math": "TOÁN", "emotion": "CẢM XÚC",
    "food": "ẨM THỰC", "music": "ÂM NHẠC", "place": "ĐỊA ĐIỂM",
    "nature": "KHÁM PHÁ", "identity": "PANDA", "chat": "TRÒ CHUYỆN",
    "story": "TRUYỆN", "sport": "THỂ THAO", "animal": "ĐỘNG VẬT",
    "study": "HỌC TẬP", "tech": "CÔNG NGHỆ", "people": "CON NGƯỜI",
    "game": "GAME", "science": "KHOA HỌC", "history": "LỊCH SỬ",
    "geography": "ĐỊA LÝ", "space": "VŨ TRỤ", "health": "SỨC KHỎE",
    "money": "TIỀN", "movie": "PHIM",
}


def classify_topic(question: str) -> str:
    """Trả về id chủ đề của câu hỏi; không khớp → 'chat'.
    Keyword ngắn (≤3 ký tự, vd 'cá') phải khớp NGUYÊN TỪ — tránh bắt
    nhầm trong từ dài ('cá' trong 'cách')."""
    q = (question or "").lower()
    for tid, kws in TOPICS:
        for k in kws:
            if len(k) <= 3:
                if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", q):
                    return tid
            elif k in q:
                return tid
    return DEFAULT_TOPIC
