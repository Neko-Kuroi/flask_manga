import os

# ベースディレクトリの定義
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# データベース設定
DATABASE = os.path.join(BASE_DIR, 'manga.db')

# キャッシュディレクトリ設定
MANGA_CACHE_DIR = os.path.join(BASE_DIR, 'manga_cache')
MANGA_CACHE_TEMP_DIR = os.path.join(BASE_DIR, 'manga_cache_temp')
CACHE_SIZE_LIMIT_MB = 270  # キャッシュの最大サイズ（MB）

# リーダー設定
IMAGES_PER_LOAD = 5        # 一度に読み込む画像の枚数

# セキュリティ設定
# !!! 本番環境では、以下の値を環境変数から読み込むなどして安全に設定してください !!!
# 例: os.environ.get('FLASK_SECRET_KEY', 'デフォルトの秘密鍵_開発用')
FLASK_SECRET_KEY = 'your_super_secret_and_complex_key_here_please_change'

# 外部からのダウンロードを許可するドメインのホワイトリスト
# 例: ALLOWED_DOMAINS = ['example.com', 'trusted-site.com']
# 空のリストにすると、どのドメインからでもダウンロードを許可します（セキュリティリスクを理解した上で使用してください）。
ALLOWED_DOMAINS = []

# ダウンロードするファイルの最大サイズ（MB） - DoS攻撃対策
MAX_DOWNLOAD_SIZE_MB = 500 # 500MB