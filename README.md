# flask_manga
Flask manga

以下は、**Flask アプリケーションの構成ファイルとテンプレート**についての **説明**です。このアプリケーションは、ZIP/CBZ/RAR 形式のマンガアーカイブをオンラインで閲覧できる「マンガビューアー」です。

---

## 📁 ファイル構成

```
manga_viewer/
├── app.py                  # Flask アプリ本体
├── config.py               # 設定ファイル
├── templates/
│   ├── index.html          # トップページ（追加フォーム + マンガ一覧）
│   ├── manga_list.html     # マンガリスト部分（HTMX用）
│   ├── reader.html         # リーダーページ
│   └── reader_content.html # 実際の画像表示部分
├── manga.db                # SQLite データベース
├── manga_cache/            # 解凍後の画像キャッシュ
└── manga_cache_temp/       # 一時解凍ディレクトリ
```

---

## ✅ 1. `app.py` — Flask アプリ本体

### 🔧 主要機能

- ZIP/CBZ/RAR 形式の漫画を URL からダウンロードして展開。
- 画像を WebP/PNG 形式に変換してキャッシュ。
- セッション管理で現在読んでいる漫画を保持。
- HTMX / AJAX を使用して動的読み込み。
- キャッシュ自動削除（LRU方式）。
- RAR 対応（`unrar` コマンドが必要）。

### 🧱 主なルート

| ルート | 機能 |
|-------|------|
| `/` | トップページ |
| `/add` | 新しいマンガを追加（POST） |
| `/remove` | マンガを削除（POST） |
| `/read` | 選択したマンガを開く |
| `/reader` | リーダーページ |
| `/reader_data` | イメージパスを取得し、HTML 表示 |
| `/get_images` | JSON 形式で画像 URL を返す |
| `/image/<path>` | キャッシュ内の画像を配信 |
| `/clear_cache` | キャッシュ全削除 |

### 🔐 セキュリティ対策

- URL 検証（HTTP(S) 制限 + ドメインホワイトリスト）
- パストラバーサル防止（`../` 禁止）
- ダウンロードサイズ制限
- セッションベースの現在読み込み中マンガ管理

---

## ✅ 2. `config.py` — 設定ファイル

```python
DATABASE = 'manga.db'
MANGA_CACHE_DIR = 'manga_cache'
MANGA_CACHE_TEMP_DIR = 'manga_cache_temp'
CACHE_SIZE_LIMIT_MB = 270
IMAGES_PER_LOAD = 5
ALLOWED_DOMAINS = ['example.com', 'trusted-site.com']
FLASK_SECRET_KEY = 'your_super_secret_and_complex_key_here_please_change'
MAX_DOWNLOAD_SIZE_MB = 500
```

### 🔒 主な設定項目

| 設定名 | 内容 |
|--------|------|
| `DATABASE` | SQLite データベースファイルの場所 |
| `MANGA_CACHE_DIR` | 解凍済み画像の保存先 |
| `CACHE_SIZE_LIMIT_MB` | キャッシュ最大容量（MB） |
| `IMAGES_PER_LOAD` | 一度に読み込む画像数 |
| `ALLOWED_DOMAINS` | ダウンロード許可するドメイン（空リスト = 全て許可） |
| `FLASK_SECRET_KEY` | Flask のセッション暗号化キー |
| `MAX_DOWNLOAD_SIZE_MB` | 一度にダウンロード可能な最大サイズ（DoS 攻撃対策） |

> 💡 **注意**: 本番環境では `FLASK_SECRET_KEY` などは **環境変数** で管理してください。

---

## ✅ 3. `templates/index.html` — トップページ

### 📋 特徴

- Tailwind CSS によるレスポンシブデザイン
- HTMX を使った非同期追加・削除
- ローディングインジケーター付きボタン
- キャッシュクリアボタン（確認ダイアログ付き）

### 🎯 主な要素

```html
<form hx-post="/add" ...>
  <input type="url" name="manga_url" placeholder="ZIP/RAR 直リンク">
  <button type="submit">追加</button>
</form>

<div id="manga-list"
     hx-get="/manga_list"
     hx-trigger="load">
  <!-- manga_list.html がここに挿入される -->
</div>
```

---

## ✅ 4. `templates/manga_list.html` — マンガ一覧部分（HTMX）

### 📋 特徴

- グリッドレイアウト（PC: 最大3列 / スマホ: 1列）
- 「読む」「削除」ボタン付き
- 削除時は確認ダイアログ
- base64 エンコードされた URL で遷移

### 🎯 主な構造

```html
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  {% for manga in mangas %}
    <div class="card">
      <p>{{ manga.title }}</p>
      <a href="/read?url_b64={{ base64.b64encode(manga.url.encode()).decode() }}">読む</a>
      <button hx-post="/remove" hx-vals='{"url":"{{ manga.url }}"'>削除</button>
    </div>
  {% endfor %}
</div>
```

---

## ✅ 5. `templates/reader.html` — リーダーページ

### 📋 特徴

- ヘッダーに「リストに戻る」リンク
- `/reader_data` から画像データを非同期取得
- 動的に `_reader_content.html` を挿入
- JavaScript または HTMX で実装可能

### 🎯 主な構造

```html
<a href="/">↩️ リストに戻る</a>
<h1>{{ title }}</h1>
<div id="reader-content" hx-get="/reader_data"></div>
```

---

## ✅ 6. `templates/reader_content.html` — 画像表示部分

### 📋 特徴

- 「ページ X / Y」表示
- 「もっと読み込む」ボタン（AJAX）
- lazy loading 対応の `<img>` タグ
- JavaScript で画像を非同期読み込み

### 🎯 主な構造

```html
<p>ページ <span id="loaded">0</span> / <span id="total">{{ total_pages }}</span></p>
<div id="image-container"></div>
<button id="load-more">▼ もっと読み込む</button>
```

### 🧠 JavaScript 動作

```javascript
fetch(`/get_images?offset=${currentOffset}`)
  .then(response => response.json())
  .then(data => {
    data.images.forEach(src => {
      const img = document.createElement('img');
      img.src = src;
      imageContainer.appendChild(img);
    });
  });
```

---

## ✅ まとめ：各ファイルの役割

| ファイル | 役割 |
|----------|------|
| `app.py` | Flask アプリ本体、ルート、ビジネスロジック |
| `config.py` | アプリ全体の設定（パス、セキュリティ、キャッシュなど） |
| `index.html` | メイン画面（追加フォーム + マンガ一覧表示領域） |
| `manga_list.html` | HTMX で呼び出されるマンガカード一覧部分 |
| `reader.html` | リーダーページ（タイトル + 画像表示領域） |
| `reader_content.html` | 実際の画像タグやページネーション情報 |
| `SQLite DB` | マンガのメタ情報を保存（URL, ハッシュ, タイトル, 拡張子） |
| `manga_cache/` | 解凍後の画像を WebP/PNG 形式でキャッシュ |
| `manga_cache_temp/` | RAR 解凍時の一時ディレクトリ |

---
