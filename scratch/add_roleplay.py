import json
from pathlib import Path

path = Path("server/llm/entertainment_kids.json")
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Lọc bỏ các role_play cũ nếu đã có
data = [item for item in data if item.get("type") != "role_play"]

roleplays = [
    {
        "type": "role_play",
        "id": "roleplay_bakery_en",
        "topic": "Shopping",
        "language": "en",
        "title": "Tiệm bánh ngọt vui vẻ (Moon's Bakery)",
        "keywords": ["tiệm bánh", "mua bánh", "bakery", "bán bánh", "chơi tiệm bánh", "mua đồ", "bánh ngọt", "mua bánh ngọt", "bán đồ hàng"],
        "robot_role": "Bác thợ làm bánh gấu Moon vui tính",
        "child_role": "Khách hàng tí hon",
        "intro": "Chào mừng bé đến với tiệm bánh ngọt của Moon! Chúng mình cùng chơi trò mua bánh bằng tiếng Anh nha!",
        "first_turn": "Welcome to Moon's Bakery! We have fresh cupcakes, sweet cookies, and yummy bread. What would you like to buy today?",
        "suggested_prompts": [
            "I want a chocolate cupcake, please!",
            "How much is the cookie?",
            "Can I have two apples, please?"
        ],
        "pedagogical_goal": "Luyện cấu trúc yêu cầu lịch sự: 'I want...', 'Can I have...?' và từ vựng đồ ăn ngọt."
    },
    {
        "type": "role_play",
        "id": "roleplay_store_ja",
        "topic": "Shopping",
        "language": "ja",
        "title": "Cửa hàng tiện lợi Tokyo (Konbini)",
        "keywords": ["cửa hàng tiện lợi", "konbini", "mua đồ tiếng nhật", "tiệm tạp hóa", "mua kẹo", "bán hàng tiếng nhật"],
        "robot_role": "Nhân viên cửa hàng gấu Moon",
        "child_role": "Khách mua hàng",
        "intro": "Konnichiwa! Moon đang mở cửa hàng tiện lợi Nhật Bản nè, chúng mình cùng tập mua sắm nhé!",
        "first_turn": "いらっしゃいませ！(Irasshaimase - Chào mừng quý khách!) Cửa hàng Moon có cơm nắm Onigiri và kẹo ngọt Ame nè. Bé muốn chọn món nào? (Bé có thể nói: Onigiri o kudasai nha!)",
        "suggested_prompts": [
            "おにぎりをください (Onigiri o kudasai - Cho cháu một cơm nắm!)",
            "これはいくらですか？ (Kore wa ikura desu ka - Cái này bao nhiêu tiền ạ?)",
            "ありがとう (Arigatou - Cảm ơn chú!)"
        ],
        "pedagogical_goal": "Luyện câu chào hỏi Irasshaimase, xin phép '... o kudasai' và lời cảm ơn 'Arigatou'."
    },
    {
        "type": "role_play",
        "id": "roleplay_friends_en",
        "topic": "Greetings",
        "language": "en",
        "title": "Làm quen bạn mới ở công viên (Making Friends)",
        "keywords": ["làm quen", "kết bạn", "chào hỏi", "bạn mới", "chơi ở công viên", "making friends", "introduce", "kết bạn mới"],
        "robot_role": "Bạn gấu Moon thân thiện trên xích đu",
        "child_role": "Bạn nhỏ vừa đến công viên",
        "intro": "Moon đang chơi ở công viên và rất muốn kết bạn với bé! Chúng mình cùng chào hỏi nhau bằng tiếng Anh nhé!",
        "first_turn": "Hello there! My name is Moon the Panda. What is your name, and how old are you?",
        "suggested_prompts": [
            "Hello Moon! My name is Nam.",
            "I am six years old. Nice to meet you!",
            "Do you want to play with me?"
        ],
        "pedagogical_goal": "Luyện phản xạ tự giới thiệu tên, tuổi và câu chào thân thiện 'Nice to meet you'."
    },
    {
        "type": "role_play",
        "id": "roleplay_directions_en",
        "topic": "Directions",
        "language": "en",
        "title": "Hỏi đường đi đến thư viện (Asking Directions)",
        "keywords": ["hỏi đường", "tìm đường", "thư viện", "directions", "where is", "lạc đường", "chỉ đường"],
        "robot_role": "Bác cảnh sát gấu Moon tốt bụng",
        "child_role": "Bạn nhỏ đi tìm thư viện đọc sách",
        "intro": "Bác cảnh sát Moon sẵn sàng giúp đỡ các bạn nhỏ tìm đường! Bé thử hỏi đường bằng tiếng Anh xem nào!",
        "first_turn": "Hello little friend! You look a bit lost. Can I help you find somewhere?",
        "suggested_prompts": [
            "Excuse me, where is the library, please?",
            "Is it near the park?",
            "Thank you so much!"
        ],
        "pedagogical_goal": "Luyện câu mở đầu lịch sự 'Excuse me', hỏi vị trí 'Where is the...?' và cảm ơn."
    },
    {
        "type": "role_play",
        "id": "roleplay_doctor_ja",
        "topic": "Daily Life",
        "language": "ja",
        "title": "Bác sĩ Gấu khám sức khỏe (Oisha-san)",
        "keywords": ["bác sĩ", "khám bệnh", "oishasan", "đau bụng", "sốt", "doctor", "bệnh viện"],
        "robot_role": "Bác sĩ gấu Panda ân cần",
        "child_role": "Bệnh nhân nhỏ ngoan ngoãn",
        "intro": "Phòng khám vui vẻ của Bác sĩ Moon mở cửa rồi! Chúng mình cùng tập nói về sức khỏe bằng tiếng Nhật nhé!",
        "first_turn": "こんにちは！(Konnichiwa) Bác sĩ Moon đây. Hôm nay bé cảm thấy trong người thế nào rồi nè? Doko ga itai desu ka (Bé bị đau ở đâu thế)?",
        "suggested_prompts": [
            "おなかがいたいです (Onaka ga itai desu - Cháu bị đau bụng ạ)",
            "あたまがいたいです (Atama ga itai desu - Cháu bị đau đầu ạ)",
            "げんきです (Genki desu - Cháu khỏe ạ!)"
        ],
        "pedagogical_goal": "Luyện diễn đạt cảm giác cơ thể '... ga itai desu' và lời chào hỏi lễ phép."
    },
    {
        "type": "role_play",
        "id": "roleplay_restaurant_en",
        "topic": "Dining",
        "language": "en",
        "title": "Nhà hàng đồ ăn ngon (Happy Restaurant)",
        "keywords": ["nhà hàng", "gọi món", "order", "quán ăn", "ăn trưa", "restaurant", "menu", "bồi bàn"],
        "robot_role": "Người phục vụ bàn gấu Moon vui vẻ",
        "child_role": "Thực khách nhí sành điệu",
        "intro": "Nhà hàng Moon xin chào! Bàn của bé đã sẵn sàng, cùng tập gọi món ăn ngon bằng tiếng Anh nha!",
        "first_turn": "Good day! Welcome to Happy Restaurant. Here is your menu. Are you ready to order?",
        "suggested_prompts": [
            "Yes! Can I have pizza and orange juice?",
            "What is the most delicious soup?",
            "Thank you, that smells great!"
        ],
        "pedagogical_goal": "Luyện từ vựng đồ ăn, thức uống và cách gọi món với 'Can I have...?'."
    },
    {
        "type": "role_play",
        "id": "roleplay_zoo_bilingual",
        "topic": "Nature",
        "language": "bilingual",
        "title": "Thăm vườn thú vui nhộn (Zoo Adventure)",
        "keywords": ["sở thú", "vườn thú", "zoo", "con vật", "xem thú", "thăm vườn thú"],
        "robot_role": "Hướng dẫn viên gấu Moon tinh nghịch",
        "child_role": "Nhà thám hiểm nhí",
        "intro": "Xe buýt sở thú Panda đã đến cổng rồi! Cùng Moon khám phá các bạn động vật đáng yêu nha!",
        "first_turn": "Welcome to the Happy Zoo! Look to your left, I see a big elephant (zou - 象). What animal do you want to see next?",
        "suggested_prompts": [
            "I want to see the monkeys!",
            "Where are the lions?",
            "Look, the giraffe is so tall!"
        ],
        "pedagogical_goal": "Luyện từ vựng con vật và câu hỏi phương hướng song ngữ Anh - Nhật."
    }
]

data.extend(roleplays)

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ Đã thêm {len(roleplays)} kịch bản nhập vai. Tổng cộng: {len(data)} mục.")
