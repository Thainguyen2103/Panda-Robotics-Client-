import json
import os
import sys
import numpy as np
from pathlib import Path
from rag_engine import MoonRAG, EMBEDDINGS_CACHE_PATH

def main():
    print("🚀 [PRECOMPUTE] Đang khởi tạo model multilingual-e5-small...")
    rag = MoonRAG()
    
    # Ép buộc xoá cache cũ nếu có để tính toán lại từ đầu
    if os.path.exists(EMBEDDINGS_CACHE_PATH):
        os.remove(EMBEDDINGS_CACHE_PATH)
        print("🗑️  [PRECOMPUTE] Đã xóa cache cũ.")

    print(f"📚 [PRECOMPUTE] Bắt đầu mã hóa {len(rag.knowledge_base)} dòng dữ liệu từ data.json...")
    
    # Việc truy cập rag._embeddings lần đầu tiên sẽ kích hoạt hàm _build_embeddings() ngầm định
    # vì cache đã bị xóa.
    _ = rag._embeddings
    
    if os.path.exists(EMBEDDINGS_CACHE_PATH):
        print(f"✅ [PRECOMPUTE] HOÀN TẤT! Vector Embeddings (.npz) đã được lưu tĩnh tại: {EMBEDDINGS_CACHE_PATH}")
        print("💡 Khi khởi động brain.py, hệ thống sẽ nạp file này thẳng lên RAM trong < 1ms, bỏ qua bước tính toán.")
    else:
        print("⚠️ [PRECOMPUTE] Lỗi: Không thấy file cache được tạo ra.")
        sys.exit(1)

if __name__ == "__main__":
    main()
