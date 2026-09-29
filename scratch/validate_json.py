import json
import re

file_path = "server/llm/entertainment_kids.json"

with open(file_path, "r", encoding="utf-8-sig") as f:
    text = f.read()

# Fix missing commas between objects
# If there is a } followed by { with only whitespace between them, add a comma
fixed_text = re.sub(r'\}\s*\{', '},\n  {', text)

try:
    data = json.loads(fixed_text)
    print("JSON parsed successfully after fixing commas.")
except Exception as e:
    print(f"Failed to parse JSON even after fixing: {e}")
    # Maybe missing closing bracket? Let's check
    if not fixed_text.strip().endswith(']'):
        fixed_text += '\n]'
        try:
            data = json.loads(fixed_text)
            print("JSON parsed successfully after adding ].")
        except Exception as e2:
            print(f"Still failed: {e2}")
            exit(1)

# Check for duplicates
seen = set()
duplicates = 0
unique_data = []

for item in data:
    if item['type'] == 'fact':
        key = item['content'].strip().lower()
    else:
        key = item['question'].strip().lower()
        
    if key in seen:
        duplicates += 1
    else:
        seen.add(key)
        unique_data.append(item)

print(f"Found {duplicates} duplicates.")

# Save back
with open(file_path, "w", encoding="utf-8") as f:
    json.dump(unique_data, f, ensure_ascii=False, indent=2)
print(f"Saved {len(unique_data)} unique items.")
