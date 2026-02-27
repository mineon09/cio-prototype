import re
with open("ionq_test.htm", "r", encoding="utf-8") as f:
    text = f.read()

text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL|re.IGNORECASE)
print(f"After script/style strip: {len(text)}")
text = re.sub(r'<[^>]+>', ' ', text)
print(f"After tag strip: {len(text)}")
text = re.sub(r'\s+', ' ', text).strip()
print(f"Final length: {len(text)}")
print("Sample:", text[:200])
