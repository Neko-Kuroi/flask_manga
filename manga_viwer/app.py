from flask import Flask, request, render_template, redirect, url_for, session, send_file, abort, jsonify, g
import os
import hashlib
import base64
import zipfile
import subprocess
import shutil
from urllib.parse import urlparse, unquote
import requests
from PIL import Image
import glob
import re
import sqlite3
import logging # ロギングを追加

# config.pyから設定をインポート
from config import (
    DATABASE,
    MANGA_CACHE_DIR,
    MANGA_CACHE_TEMP_DIR,
    CACHE_SIZE_LIMIT_MB,
    IMAGES_PER_LOAD,
    ALLOWED_DOMAINS,
    FLASK_SECRET_KEY,
    MAX_DOWNLOAD_SIZE_MB
)

# Flaskアプリケーションの初期化
app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY # configから秘密鍵を設定

# ロギングの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 初期化: キャッシュディレクトリの作成
os.makedirs(MANGA_CACHE_DIR, exist_ok=True)
os.makedirs(MANGA_CACHE_TEMP_DIR, exist_ok=True)

# データベース接続のヘルパー関数
def get_db():
    """データベース接続を取得または作成する"""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row # カラム名でアクセスできるようにする
    return g.db

@app.teardown_appcontext
def close_db(exception):
    """リクエスト終了時にデータベース接続を閉じる"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

# データベース初期化
def init_db():
    """データベーススキーマを初期化する"""
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS mangas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash TEXT UNIQUE,
                url TEXT,
                title TEXT,
                file_ext TEXT
            )
        ''')
        db.commit()

init_db() # アプリケーション起動時にデータベースを初期化

# ヘルパー関数: URLの安全性を検証
def is_valid_url(url):
    """
    URLが有効で、許可されたドメインに属するかどうかを検証する。
    """
    try:
        result = urlparse(url)
        # スキームがHTTP/HTTPSであり、ネットロケーションが存在するか
        if not all([result.scheme in ['http', 'https'], result.netloc]):
            logging.warning(f"無効なURLスキームまたはネットロケーション: {url}")
            return False

        domain = result.netloc
        # 許可されたドメインリストが設定されており、ドメインがリストにない場合
        if ALLOWED_DOMAINS and domain not in ALLOWED_DOMAINS:
            logging.warning(f"許可されていないドメインからのURL: {url} (ドメイン: {domain})")
            return False
        return True
    except Exception as e:
        logging.error(f"URL検証エラー: {e} (URL: {url})", exc_info=True)
        return False

# ヘルパー関数: ファイルのダウンロード
def download_file(url, save_path):
    """
    指定されたURLからファイルをダウンロードする。
    既にファイルが存在する場合はスキップする。
    """
    if os.path.exists(save_path):
        logging.info(f"ファイルは既に存在します: {save_path}")
        return

    headers = {'User-Agent': 'MangaViewer/1.0'}
    try:
        with requests.get(url, stream=True, headers=headers, timeout=120) as r:
            r.raise_for_status() # HTTPエラーが発生した場合に例外を発生させる

            downloaded_size = 0
            max_bytes = MAX_DOWNLOAD_SIZE_MB * 1024 * 1024

            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    downloaded_size += len(chunk)
                    if downloaded_size > max_bytes:
                        os.remove(save_path) # 中途半端なファイルを削除
                        logging.error(f"ファイルサイズが制限を超過しました: {url}")
                        raise Exception(f"ファイルサイズが{MAX_DOWNLOAD_SIZE_MB}MBを超過しました。")
                    f.write(chunk)
        logging.info(f"ファイルのダウンロードが完了しました: {url} -> {save_path}")
    except requests.exceptions.RequestException as e:
        logging.error(f"ファイルダウンロードエラー: {e} (URL: {url})", exc_info=True)
        # ダウンロード失敗時にファイルを削除（部分的にダウンロードされた場合）
        if os.path.exists(save_path):
            os.remove(save_path)
        raise
    except Exception as e:
        logging.error(f"ファイルダウンロード中の予期せぬエラー: {e} (URL: {url})", exc_info=True)
        if os.path.exists(save_path):
            os.remove(save_path)
        raise


# ヘルパー関数: ZIPファイルの解凍と画像処理
def extract_zip(archive_path, extract_to):
    """
    ZIP/CBZファイルを解凍し、画像をWebP形式に変換して保存する。
    """
    os.makedirs(extract_to, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            # 危険なパス（..など）を防ぐため、メンバーリストをチェック
            for i, name in enumerate(zip_ref.namelist()):
                # 画像ファイルのみを対象とし、ディレクトリトラバーサルを防ぐ
                if not re.search(r'\.(jpe?g|png|gif|bmp)$', name, re.I):
                    continue
                if os.path.basename(name) != name: # サブディレクトリ内のファイルを無視
                    continue # より厳密なセキュリティが必要な場合は、サブディレクトリ内の画像も処理対象外に

                try:
                    with zip_ref.open(name) as f:
                        img = Image.open(f).convert('RGB')
                        img.thumbnail((1200, 1600)) # サムネイルサイズにリサイズ
                        # 連番でファイル名を生成し、元のファイル名を無視してセキュリティを向上
                        img.save(os.path.join(extract_to, f'{i:04d}.png'), 'PNG')
                except Exception as e:
                    logging.warning(f"画像処理エラー (ZIP): {name} - {e}", exc_info=True)
        logging.info(f"ZIP解凍と画像処理が完了しました: {archive_path} -> {extract_to}")
    except zipfile.BadZipFile as e:
        logging.error(f"破損したZIPファイル: {archive_path} - {e}", exc_info=True)
        shutil.rmtree(extract_to, ignore_errors=True) # 失敗したら抽出ディレクトリをクリーンアップ
        raise
    except Exception as e:
        logging.error(f"ZIP解凍中の予期せぬエラー: {archive_path} - {e}", exc_info=True)
        shutil.rmtree(extract_to, ignore_errors=True)
        raise

# ヘルパー関数: RARファイルの解凍と画像処理
def extract_rar(archive_path, extract_to):
    """
    RAR/CBRファイルをunrarコマンドを使用して解凍し、画像をWebP形式に変換して保存する。
    """
    temp_dir = os.path.join(MANGA_CACHE_TEMP_DIR, os.path.basename(archive_path) + '_temp')
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(extract_to, exist_ok=True)

    try:
        # unrarコマンドの引数を厳密に制御し、シェルインジェクションを防ぐ
        # `subprocess.run`はデフォルトでシェルを使用しないため、安全
        cmd = ['unrar', 'x', '-o-', archive_path, temp_dir] # -o- で上書きを避ける
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"UnRARコマンド出力:\n{result.stdout}")

        files = glob.glob(os.path.join(temp_dir, '*'))
        for i, path in enumerate(sorted(files)):
            # 画像ファイルのみを対象とする
            if not re.search(r'\.(jpe?g|png|gif|bmp)$', path, re.I):
                continue
            if not os.path.isfile(path): # ディレクトリをスキップ
                continue

            try:
                img = Image.open(path).convert('RGB')
                img.thumbnail((1200, 1600))
                img.save(os.path.join(extract_to, f'{i:04d}.png'), 'PNG')
            except Exception as e:
                logging.warning(f"画像処理エラー (RAR): {os.path.basename(path)} - {e}", exc_info=True)
        logging.info(f"RAR解凍と画像処理が完了しました: {archive_path} -> {extract_to}")
    except subprocess.CalledProcessError as e:
        logging.error(f"UnRARコマンド実行エラー: {e.stderr} (コマンド: {' '.join(cmd)})", exc_info=True)
        shutil.rmtree(extract_to, ignore_errors=True)
        raise Exception(f"RARファイルの解凍に失敗しました。unrarツールが正しくインストールされ、利用可能か確認してください。: {e.stderr}")
    except Exception as e:
        logging.error(f"RAR解凍中の予期せぬエラー: {archive_path} - {e}", exc_info=True)
        shutil.rmtree(extract_to, ignore_errors=True)
        raise
    finally:
        # 一時ディレクトリを必ずクリーンアップ
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


# ヘルパー関数: キャッシュ管理
def manage_cache_size(current_hash=None):
    """
    キャッシュディレクトリのサイズを管理し、制限を超えた場合は古いファイルを削除する。
    現在読み込んでいるマンガは削除対象外とする。
    """
    items = {} # {hash: {'mtime': latest_mtime, 'size': total_size_for_hash}}
    total_cache_size = 0 # バイト単位
    max_size_bytes = CACHE_SIZE_LIMIT_MB * 1024 * 1024

    # 全てのキャッシュアイテムを走査
    for f in os.listdir(MANGA_CACHE_DIR):
        full_path = os.path.join(MANGA_CACHE_DIR, f)
        
        # ファイル名からハッシュ部分を抽出
        # 'hash.zip' または 'hash_extracted' の形式を想定
        match = re.match(r'([0-9a-fA-F]{32})', f)
        if not match:
            # 期待しないファイルはスキップ、またはログを記録
            logging.debug(f"キャッシュディレクトリ内で不明な形式のファイルを発見: {f}")
            continue
        
        item_hash = match.group(1)

        size = 0
        mtime = 0

        if os.path.isfile(full_path):
            size = os.path.getsize(full_path)
            mtime = os.path.getmtime(full_path)
        elif os.path.isdir(full_path):
            # ディレクトリの場合は、その中の全ファイルの合計サイズと最新のmtime
            for r, _, files in os.walk(full_path):
                for file in files:
                    file_path = os.path.join(r, file)
                    size += os.path.getsize(file_path)
                    mtime = max(mtime, os.path.getmtime(file_path))
        else:
            continue # シンボリックリンクなどは無視

        if item_hash not in items:
            items[item_hash] = {'mtime': mtime, 'size': size}
        else:
            # 既存のハッシュアイテムの情報を更新
            items[item_hash]['mtime'] = max(items[item_hash]['mtime'], mtime)
            items[item_hash]['size'] += size
        
        total_cache_size += size

    logging.info(f"現在のキャッシュサイズ: {total_cache_size / (1024*1024):.2f}MB / 制限: {CACHE_SIZE_LIMIT_MB}MB")

    # キャッシュサイズが制限を超えていなければ終了
    if total_cache_size <= max_size_bytes:
        return

    logging.info("キャッシュサイズが制限を超過しました。古いアイテムを削除します。")

    # 最終アクセス時間が古い順にソート
    # current_hashがあれば、それをスキップするためにlambdaでフィルタリング
    sorted_hashes = sorted([h for h in items if h != current_hash], key=lambda h: items[h]['mtime'])

    for item_hash_to_delete in sorted_hashes:
        if total_cache_size <= max_size_bytes:
            break # 制限内に収まったら停止

        # 関連するファイルとディレクトリを削除
        # hash.* (例: hash.zip, hash.rar) と hash_extracted ディレクトリ
        deleted_size = items[item_hash_to_delete]['size'] # 削除されるアイテムの総サイズ

        for pattern in [f'{item_hash_to_delete}.*', f'{item_hash_to_delete}_extracted']:
            for path in glob.glob(os.path.join(MANGA_CACHE_DIR, pattern)):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                        logging.info(f"キャッシュディレクトリを削除しました: {path}")
                    elif os.path.isfile(path):
                        os.remove(path)
                        logging.info(f"キャッシュファイルを削除しました: {path}")
                except OSError as e:
                    logging.error(f"キャッシュ削除エラー: {path} - {e}", exc_info=True)
        
        total_cache_size -= deleted_size
        logging.info(f"ハッシュ {item_hash_to_delete} のキャッシュを削除しました。現在のキャッシュサイズ: {total_cache_size / (1024*1024):.2f}MB")


# --- ルート定義 ---

@app.route('/')
def index():
    """トップページ: マンガリストと追加フォームを表示する"""
    # base64モジュールをテンプレートに渡す
    return render_template('index.html', base64=base64)

@app.route('/manga_list')
def manga_list():
    """マンガリストをHTMXリクエスト用に返す"""
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM mangas ORDER BY title')
    mangas = cur.fetchall()
    return render_template('manga_list.html', mangas=mangas, base64=base64)

@app.route('/add', methods=['POST'])
def add_manga():
    """マンガをデータベースに追加する"""
    url = request.form.get('manga_url', '').strip()
    
    if not url:
        return '<p class="text-red-600">URLを入力してください。</p>'

    if not is_valid_url(url):
        return '<p class="text-red-600">無効なURL、または許可されていないドメインです。</p>'
    
    # URLから一意のハッシュを生成
    manga_hash = hashlib.md5(url.encode()).hexdigest()
    
    # ファイル名と拡張子を安全に抽出
    # werkzeug.utils.secure_filename を使用するのがより堅牢ですが、
    # ここでは basename と splitext で簡単なサニタイズを行います。
    # 完全にパストラバーサルを防ぐには、外部からのファイル名を信用しないことが重要です。
    title_raw = os.path.splitext(os.path.basename(unquote(urlparse(url).path)))[0]
    # タイトルからパス区切り文字や無効な文字を削除
    title = re.sub(r'[\\/:\*?"<>|]', '', title_raw)
    if not title: # タイトルが空になる場合に対応
        title = manga_hash[:8] # ハッシュの一部をタイトルとして使用

    ext = os.path.splitext(url)[1][1:].lower() # 拡張子から'.'を除去

    if ext not in ['zip', 'cbz', 'rar', 'cbr']:
        return '<p class="text-red-600">無効なファイル形式です。ZIP, CBZ, RAR, CBRのみがサポートされています。</p>'

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM mangas WHERE hash=?', (manga_hash,))
    if cur.fetchone():
        logging.info(f"このURLは既に追加済みです: {url}")
        return '<p class="text-red-600">このURLは既に追加済みです。</p>'
    
    try:
        cur.execute('INSERT INTO mangas (hash, url, title, file_ext) VALUES (?, ?, ?, ?)',
                    (manga_hash, url, title, ext))
        db.commit()
        logging.info(f"マンガが追加されました: {title} ({url})")
    except sqlite3.IntegrityError: # UNIQUE制約違反の場合
        logging.warning(f"マンガの追加中に整合性エラーが発生しました (重複): {url}")
        return '<p class="text-red-600">このURLは既に追加済みです。</p>'
    except Exception as e:
        db.rollback() # エラーが発生した場合はロールバック
        logging.error(f"マンガの追加中にデータベースエラーが発生しました: {e}", exc_info=True)
        return '<p class="text-red-600">マンガの追加中にエラーが発生しました。</p>'

    return '<p class="text-green-600">マンガが正常に追加されました。</p>'

@app.route('/remove', methods=['POST'])
def remove_manga():
    """マンガをデータベースから削除する"""
    url = request.form.get('url', '').strip()
    if not url:
        logging.warning("削除リクエストにURLが指定されていません。")
        return '<p class="text-red-600">削除対象のURLが指定されていません。</p>'

    manga_hash = hashlib.md5(url.encode()).hexdigest()
    
    db = get_db()
    try:
        db.execute('DELETE FROM mangas WHERE hash=?', (manga_hash,))
        db.commit()
        logging.info(f"マンガが削除されました (hash: {manga_hash}, url: {url})")
    except Exception as e:
        db.rollback()
        logging.error(f"マンガ削除中にデータベースエラーが発生しました: {e}", exc_info=True)
        return '<p class="text-red-600">マンガの削除中にエラーが発生しました。</p>'

    # 削除後、最新のリストを返す
    cur = db.cursor()
    cur.execute('SELECT * FROM mangas ORDER BY title')
    mangas = cur.fetchall()
    return render_template('manga_list.html', mangas=mangas, base64=base64) # base64を渡す

@app.route('/read')
def read_manga():
    """選択されたマンガのリーダーページへリダイレクトする"""
    url_b64 = request.args.get('url_b64', '')
    if not url_b64:
        logging.warning("readリクエストにurl_b64パラメータがありません。")
        return redirect(url_for('index'))
    
    try:
        # URLセーフなBase64をデコード
        url = base64.b64decode(url_b64.replace('-', '+').replace('_', '/')).decode('utf-8')
        manga_hash = hashlib.md5(url.encode()).hexdigest()
        
        db = get_db()
        cur = db.cursor()
        cur.execute('SELECT * FROM mangas WHERE hash=?', (manga_hash,))
        manga_row = cur.fetchone()
        
        if not manga_row:
            logging.warning(f"データベースに存在しないマンガの読み込みリクエスト: {url_b64}")
            return redirect(url_for('index'))
        
        # セッションにマンガのハッシュを保存
        session['selected_manga_hash'] = manga_hash
        logging.info(f"マンガリーダーへリダイレクト: {manga_row['title']} (hash: {manga_hash})")
        return redirect(url_for('reader'))
    except Exception as e:
        logging.error(f"マンガ読み込みリクエスト処理エラー: {e} (url_b64: {url_b64})", exc_info=True)
        return redirect(url_for('index'))

@app.route('/reader')
def reader():
    """マンガリーダーのメインページを表示する"""
    manga_hash = session.get('selected_manga_hash')
    if not manga_hash:
        logging.warning("セッションにマンガハッシュがありません。インデックスにリダイレクトします。")
        return redirect(url_for('index'))
    
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT title FROM mangas WHERE hash=?', (manga_hash,))
    row = cur.fetchone()
    
    if not row:
        logging.warning(f"データベースに存在しないマンガがセッションに記録されています: {manga_hash}")
        session.pop('selected_manga_hash', None) # 無効なセッションデータをクリア
        return redirect(url_for('index'))
    
    title = row['title']
    logging.info(f"リーダーページ表示: {title} (hash: {manga_hash})")
    return render_template('reader.html', title=title)

@app.route('/reader_data')
def reader_data():
    """マンガのデータ（画像パス）を準備し、reader_content.htmlを返す"""
    manga_hash = session.get('selected_manga_hash')
    if not manga_hash:
        logging.error("reader_dataリクエストでマンガハッシュが見つかりません。")
        abort(404) # Not Found

    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT url, title, file_ext FROM mangas WHERE hash=?', (manga_hash,))
    row = cur.fetchone()
    
    if not row:
        logging.error(f"データベースに存在しないマンガのreader_dataリクエスト: {manga_hash}")
        abort(404)

    url = row['url']
    title = row['title']
    ext = row['file_ext']

    archive_path = os.path.join(MANGA_CACHE_DIR, f'{manga_hash}.{ext}')
    extract_path = os.path.join(MANGA_CACHE_DIR, f'{manga_hash}_extracted')

    # キャッシュサイズの管理（現在読み込んでいるマンガは削除対象外）
    manage_cache_size(manga_hash)

    # 抽出ディレクトリが存在しない、または画像が一つもない場合のみ処理
    if not os.path.isdir(extract_path) or len(glob.glob(f'{extract_path}/*.png')) == 0:
        logging.info(f"マンガをダウンロード/抽出します: {title} (hash: {manga_hash})")
        try:
            download_file(url, archive_path)
            # 既に抽出ディレクトリが存在する場合は、古い内容を削除して再抽出
            if os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            
            if ext in ['zip', 'cbz']:
                extract_zip(archive_path, extract_path)
            elif ext in ['rar', 'cbr']:
                extract_rar(archive_path, extract_path)
            else:
                logging.error(f"未対応のファイル拡張子: {ext}")
                abort(500, "未対応のファイル形式です。")
        except Exception as e:
            logging.error(f"マンガのダウンロードまたは抽出に失敗しました: {title} - {e}", exc_info=True)
            # エラー発生時は、不完全なキャッシュをクリーンアップ
            if os.path.exists(archive_path):
                os.remove(archive_path)
            if os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            abort(500, f"マンガの読み込み中にエラーが発生しました: {e}")
    else:
        logging.info(f"キャッシュからマンガをロードします: {title} (hash: {manga_hash})")


    images = sorted(glob.glob(f'{extract_path}/*.png'))
    if not images:
        logging.error(f"抽出された画像が見つかりません: {extract_path}")
        # 画像がない場合、キャッシュをクリーンアップして再試行を促す
        if os.path.exists(archive_path):
            os.remove(archive_path)
        if os.path.exists(extract_path):
            shutil.rmtree(extract_path)
        abort(404, "マンガの画像が見つかりませんでした。再度追加してみてください。")

    session['current_manga_images'] = [os.path.relpath(p, MANGA_CACHE_DIR) for p in images]
    session['current_manga_hash'] = manga_hash # 現在読み込んでいるマンガのハッシュをセッションに保存
    logging.info(f"reader_content.htmlをレンダリングします。総ページ数: {len(images)}")
    return render_template('reader_content.html', title=title, total_pages=len(images), offset=0)

@app.route('/get_images')
def get_images():
    """マンガ画像をチャンクで返す（AJAX用）"""
    images_relative_paths = session.get('current_manga_images', [])
    manga_hash = session.get('current_manga_hash') # キャッシュ管理のためにハッシュも取得

    if not images_relative_paths or not manga_hash:
        logging.warning("get_imagesリクエストでセッションデータが見つかりません。")
        return jsonify({'images': [], 'current_offset': 0, 'total_pages': 0}), 404

    offset = int(request.args.get('offset', 0))
    
    # 最後にアクセスしたマンガとしてキャッシュ管理に反映
    manage_cache_size(manga_hash)

    slice_ = images_relative_paths[offset:offset+IMAGES_PER_LOAD]
    
    # 画像のURLを生成
    image_urls = [f'/image/{p}' for p in slice_]

    logging.debug(f"画像を提供中: オフセット {offset}, 取得枚数 {len(slice_)}")
    return jsonify({
        'images': image_urls,
        'current_offset': offset,
        'total_pages': len(images_relative_paths)
    })

@app.route('/image/<path:path>')
def serve_image(path):
    """キャッシュディレクトリから画像ファイルを安全に提供する"""
    # pathはMANGA_CACHE_DIRからの相対パスとして解釈される
    full_path = os.path.join(MANGA_CACHE_DIR, path)

    # パストラバーサル攻撃を防ぐためのチェック
    # MANGA_CACHE_DIRの外へのアクセスを禁止する
    if not os.path.abspath(full_path).startswith(os.path.abspath(MANGA_CACHE_DIR)):
        logging.warning(f"不正な画像パスアクセス試行: {path}")
        abort(403) # Forbidden

    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        logging.warning(f"画像ファイルが見つかりません: {full_path}")
        abort(404)
    
    # MIMEタイプを適切に推測する (例: image/webp)
    # python-magicを使っていればより正確ですが、ここでは拡張子から推測
    mime_type = "image/png" # 現状はすべてpngで保存されるため固定
    
    return send_file(full_path, mimetype=mime_type)

@app.route('/clear_cache', methods=['POST'])
def clear_cache():
    """全キャッシュを削除する（開発/デバッグ用、注意して使用）"""
    logging.info("キャッシュクリアリクエストを受信しました。")
    try:
        # MANGA_CACHE_DIR内の全てのファイルとディレクトリを削除
        for f in os.listdir(MANGA_CACHE_DIR):
            path = os.path.join(MANGA_CACHE_DIR, f)
            if os.path.isfile(path):
                os.remove(path)
                logging.info(f"キャッシュファイルを削除しました: {path}")
            elif os.path.isdir(path):
                shutil.rmtree(path)
                logging.info(f"キャッシュディレクトリを削除しました: {path}")
        
        # MANGA_CACHE_TEMP_DIRもクリア
        if os.path.exists(MANGA_CACHE_TEMP_DIR):
            shutil.rmtree(MANGA_CACHE_TEMP_DIR)
            os.makedirs(MANGA_CACHE_TEMP_DIR) # 空のディレクトリを再作成
            logging.info(f"一時キャッシュディレクトリをクリアしました: {MANGA_CACHE_TEMP_DIR}")

        logging.info("全キャッシュが正常にクリアされました。")
        return jsonify({'success': True}), 200
    except Exception as e:
        logging.error(f"キャッシュクリア中にエラーが発生しました: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # 開発環境向け: デバッグモードを有効にする
    # 本番環境では False に設定するか、WSGIサーバーを使用してください
    app.run(debug=True)