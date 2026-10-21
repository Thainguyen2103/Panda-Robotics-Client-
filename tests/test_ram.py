import time
from server.llm.moon_tutor import warmup_model, unload_model
import urllib.request
import json

def check_ram():
    try:
        req = urllib.request.Request('http://127.0.0.1:11434/api/ps')
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        models = data.get('models', [])
        if models:
            for m in models:
                size_gb = m.get('size', 0) / (1024**3)
                print(f"   -> Đang chạy trong RAM: {m.get('name')} (Chiếm {size_gb:.2f} GB)")
        else:
            print("   -> RAM TRỐNG (Không có model nào đang chạy)")
    except Exception as e:
        print("   -> Lỗi kiểm tra RAM:", e)

print("\n--- TRƯỚC KHI LOAD ---")
check_ram()

print("\n--- GỌI LỆNH LOAD MODEL (warmup_model) ---")
warmup_model()
check_ram()

print("\n--- CHỜ 5 GIÂY RỒI GỌI LỆNH UNLOAD ---")
time.sleep(5)
unload_model()

print("\n--- SAU KHI UNLOAD ---")
check_ram()
