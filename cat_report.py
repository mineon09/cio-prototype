
try:
    with open("debug_log.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()
except:
    try:
        with open("debug_log.txt", "r", encoding="utf-16le") as f:
            lines = f.readlines()
    except:
        try:
             with open("debug_log.txt", "r", encoding="cp932", errors="ignore") as f:
                lines = f.readlines()
        except:
             lines = ["Could not read file."]

print("Last 20 lines:")
for line in lines[-20:]:
    print(line.rstrip())
