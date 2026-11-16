import os
import yaml

# Update this path to point to your chatbot-sis-trisakti/domain folder
DOMAIN_DIR = "../chatbot-sis-trisakti/domain"
extracted_lines = []

for root, _, files in os.walk(DOMAIN_DIR):
    for file in sorted(files):
        if file.endswith(".yml"):
            role = os.path.basename(root)
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                responses = data.get("responses", {})
                for key, items in responses.items():
                    if key.startswith("utter_answer_"):
                        for item in items:
                            text = item.get("text") or item.get("translation", {}).get("id", "")
                            if text:
                                extracted_lines.append(f"[{role.upper()} - {key}]\n{text.strip()}\n")

with open("migrated_rasa_kb.txt", "w", encoding="utf-8") as out:
    out.write("\n---\n".join(extracted_lines))

print(f"Done! Extracted {len(extracted_lines)} answers into migrated_rasa_kb.txt")
