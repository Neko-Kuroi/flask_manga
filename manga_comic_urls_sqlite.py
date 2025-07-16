import json
import sqlite3

# JSONファイルを読み込む
with open('manga_comic_urls.json', 'r', encoding='utf-8') as f:
  data = json.load(f)

# SQLiteデータベースを作成（または開く）
conn = sqlite3.connect('manga_comic_urls.db')

cursor = conn.cursor() 
# テーブルを作成（存在しない場合）
cursor.execute('''
  CREATE TABLE IF NOT EXISTS comics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL
  )
''')

# データを挿入
for url, title in data.items():
  cursor.execute('''
    INSERT OR IGNORE INTO comics (url, title)
    VALUES (?, ?)
  ''', (url, title))
  # コミットして閉じる
  conn.commit()
  conn.close()

print("✅ SQLiteデータベース 'manga_comic_urls.db' が作成されました。")
