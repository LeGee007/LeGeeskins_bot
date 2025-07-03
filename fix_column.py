import sqlite3

conn = sqlite3.connect('skins.db')  # ← bu yerda sizning .db faylingiz nomi
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE skins ADD COLUMN status TEXT DEFAULT 'pending'")
    print("✅ 'status' ustuni qo‘shildi.")
except Exception as e:
    print("⚠️ Xatolik:", e)

conn.commit()
conn.close()
