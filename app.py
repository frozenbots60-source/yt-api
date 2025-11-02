# filename: app.py
from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
import requests
import hashlib
import glob
import shutil
import threading
import json
import logging
import time
import subprocess

# --- EJS FIX: Initialize Deno + yt-dlp challenge solver ---
def init_yt_dlp_solver():
    try:
        deno_version = subprocess.run(["deno", "--version"], capture_output=True, text=True)
        if deno_version.returncode == 0:
            print(f"[INIT] Deno detected: {deno_version.stdout.strip()}")
        else:
            print("[INIT] Deno not found in PATH, signature solving may fail.")
        subprocess.run(["yt-dlp", "--update-to", "nightly"], check=False)
        subprocess.run(["yt-dlp", "--rm-cache-dir"], check=False)
        subprocess.run([
            "yt-dlp",
            "--remote-components", "ejs:github",
            "--simulate", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ], check=False)
        print("[INIT] yt-dlp EJS challenge solver initialized successfully.")
    except Exception as e:
        print(f"[INIT ERROR] Failed to initialize yt-dlp EJS solver: {e}")

threading.Thread(target=init_yt_dlp_solver, daemon=True).start()
# --- END EJS FIX ---

app = Flask(__name__)

# --- Configuration ---
BASE_TEMP_DIR = "/tmp"
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

TEMP_DOWNLOAD_DIR = os.path.join(BASE_TEMP_DIR, "download")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

CACHE_DIR = os.path.join(BASE_TEMP_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

CACHE_VIDEO_DIR = os.path.join(BASE_TEMP_DIR, "cache_video")
os.makedirs(CACHE_VIDEO_DIR, exist_ok=True)

# NEW: JSON cache for /down (1-hour TTL)
CACHE_JSON_DIR = os.path.join(BASE_TEMP_DIR, "cache_json")
os.makedirs(CACHE_JSON_DIR, exist_ok=True)

MAX_CACHE_SIZE = 500 * 1024 * 1024  # 500MB

COOKIE_FILE_PATH = os.getenv("COOKIE_FILE_PATH", "cookies.txt")
if COOKIE_FILE_PATH:
    COOKIE_FILE_PATH = os.path.abspath(COOKIE_FILE_PATH)
if COOKIE_FILE_PATH and os.path.isfile(COOKIE_FILE_PATH):
    app.logger.info(f"Using cookie file at: {COOKIE_FILE_PATH}")
else:
    app.logger.warning(f"Cookie file not found or unreadable at: {COOKIE_FILE_PATH}. Continuing without cookies.")
    COOKIE_FILE_PATH = None

SEARCH_API_URL = "https://odd-block-a945.tenopno.workers.dev/search"

# --- Utility functions ---
def get_cache_key(video_url: str) -> str:
    return hashlib.md5(video_url.encode('utf-8')).hexdigest()

def get_directory_size(directory: str) -> int:
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total_size += os.path.getsize(fp)
    return total_size

def check_cache_size_and_cleanup():
    total_size = (
        get_directory_size(CACHE_DIR) +
        get_directory_size(CACHE_VIDEO_DIR) +
        get_directory_size(CACHE_JSON_DIR)
    )
    if total_size > MAX_CACHE_SIZE:
        app.logger.info(f"Cache size {total_size} exceeds {MAX_CACHE_SIZE}, clearing caches.")
        for cache_dir in [CACHE_DIR, CACHE_VIDEO_DIR, CACHE_JSON_DIR]:
            for file in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, file)
                try:
                    os.remove(file_path)
                except Exception as e:
                    app.logger.warning(f"Error deleting cache file {file_path}: {e}")

def periodic_cache_cleanup():
    while True:
        # Remove expired JSON cache entries (older than 1 hour)
        now = time.time()
        for file in os.listdir(CACHE_JSON_DIR):
            file_path = os.path.join(CACHE_JSON_DIR, file)
            try:
                if now - os.path.getmtime(file_path) > 3600:
                    os.remove(file_path)
            except Exception:
                pass
        check_cache_size_and_cleanup()
        time.sleep(60)

threading.Thread(target=periodic_cache_cleanup, daemon=True).start()

def resolve_spotify_link(url: str) -> str:
    if "spotify.com" in url:
        params = {"title": url}
        resp = requests.get(SEARCH_API_URL, params=params, timeout=15)
        if resp.status_code != 200:
            raise Exception("Failed to fetch search results for the Spotify link")
        search_result = resp.json()
        if not search_result or 'link' not in search_result:
            raise Exception("No YouTube link found for the given Spotify link")
        return search_result['link']
    return url

def make_ydl_opts_audio(output_template: str):
    ffmpeg_path = os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg")
    opts = {
        'format': 'worstaudio',
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'ffmpeg_location': ffmpeg_path,
        'concurrent_fragment_downloads': 4,
        'n_threads': 4,
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def make_ydl_opts_video(output_template: str):
    opts = {
        'format': 'worst[ext=mp4]/worst',
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'concurrent_fragment_downloads': 4,
        'n_threads': 4,
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def download_audio(video_url: str) -> str:
    cache_key = get_cache_key(video_url)
    cached_files = glob.glob(os.path.join(CACHE_DIR, f"{cache_key}.*"))
    if cached_files:
        return cached_files[0]
    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    ydl_opts = make_ydl_opts_audio(output_template)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(video_url, download=True)
            downloaded_file = ydl.prepare_filename(info)
            ext = info.get("ext", os.path.splitext(downloaded_file)[1].lstrip(".")) or "m4a"
            cached_file_path = os.path.join(CACHE_DIR, f"{cache_key}.{ext}")
            shutil.move(downloaded_file, cached_file_path)
            check_cache_size_and_cleanup()
            return cached_file_path
        except Exception as e:
            app.logger.error(f"Error downloading audio for {video_url}: {e}")
            raise Exception(f"Error downloading audio: {e}")

def download_video(video_url: str) -> str:
    cache_key = hashlib.md5((video_url + "_video").encode('utf-8')).hexdigest()
    cached_files = glob.glob(os.path.join(CACHE_VIDEO_DIR, f"{cache_key}.*"))
    if cached_files:
        return cached_files[0]
    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    ydl_opts = make_ydl_opts_video(output_template)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(video_url, download=True)
            downloaded_file = ydl.prepare_filename(info)
            cached_file_path = os.path.join(CACHE_VIDEO_DIR, f"{cache_key}.mp4")
            if os.path.abspath(downloaded_file) != os.path.abspath(cached_file_path):
                shutil.move(downloaded_file, cached_file_path)
            check_cache_size_and_cleanup()
            return cached_file_path
        except Exception as e:
            app.logger.error(f"Error downloading video for {video_url}: {e}")
            raise Exception(f"Error downloading video: {e}")

# --- Endpoints ---

@app.route('/search', methods=['GET'])
def search_video():
    try:
        query = request.args.get('title')
        if not query:
            return jsonify({"error": "The 'title' parameter is required"}), 400
        resp = requests.get(SEARCH_API_URL, params={"title": query}, timeout=15)
        if resp.status_code != 200:
            app.logger.error(f"Search API returned {resp.status_code} for query {query}")
            return jsonify({"error": "Failed to fetch search results"}), 500
        search_result = resp.json()
        if not search_result or 'link' not in search_result:
            return jsonify({"error": "No videos found for the given query"}), 404
        video_url = search_result['link']
        threading.Thread(target=download_audio, args=(video_url,), daemon=True).start()
        threading.Thread(target=download_video, args=(video_url,), daemon=True).start()
        return jsonify({
            "title": search_result.get("title"),
            "url": video_url,
            "duration": search_result.get("duration"),
        })
    except Exception as e:
        app.logger.error(f"Exception in /search: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/vdown', methods=['GET'])
def download_video_endpoint():
    try:
        video_url = request.args.get('url')
        video_title = request.args.get('title')
        if not video_url and not video_title:
            return jsonify({"error": "Either 'url' or 'title' parameter is required"}), 400
        if video_title and not video_url:
            resp = requests.get(SEARCH_API_URL, params={"title": video_title}, timeout=15)
            if resp.status_code != 200:
                app.logger.error(f"Search API error for title {video_title}: {resp.status_code}")
                return jsonify({"error": "Failed to fetch search results"}), 500
            search_result = resp.json()
            if not search_result or 'link' not in search_result:
                return jsonify({"error": "No videos found for the given query"}), 404
            video_url = search_result['link']
        if video_url and "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)
        cached_file_path = download_video(video_url)
        return send_file(cached_file_path, as_attachment=True, download_name=os.path.basename(cached_file_path))
    except Exception as e:
        app.logger.error(f"Exception in /vdown: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        for file in os.listdir(TEMP_DOWNLOAD_DIR):
            file_path = os.path.join(TEMP_DOWNLOAD_DIR, file)
            try:
                os.remove(file_path)
            except Exception:
                pass

@app.route('/download', methods=['GET'])
def download_audio_endpoint():
    try:
        video_url = request.args.get('url')
        video_title = request.args.get('title')
        if not video_url and not video_title:
            return jsonify({"error": "Either 'url' or 'title' parameter is required"}), 400
        if video_title and not video_url:
            resp = requests.get(SEARCH_API_URL, params={"title": video_title}, timeout=15)
            if resp.status_code != 200:
                return jsonify({"error": "Failed to fetch search results"}), 500
            search_result = resp.json()
            if not search_result or 'link' not in search_result:
                return jsonify({"error": "No videos found"}), 404
            video_url = search_result['link']
        if "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)
        cached_file_path = download_audio(video_url)
        return send_file(cached_file_path, as_attachment=True, download_name=os.path.basename(cached_file_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        for file in os.listdir(TEMP_DOWNLOAD_DIR):
            file_path = os.path.join(TEMP_DOWNLOAD_DIR, file)
            try:
                os.remove(file_path)
            except Exception:
                pass

# --- NEW ENDPOINT: /down with 1-hour caching ---
@app.route('/down', methods=['GET'])
def get_cdn_link():
    try:
        video_url = request.args.get('url')
        video_title = request.args.get('title')
        if not video_url and not video_title:
            return jsonify({"error": "Either 'url' or 'title' parameter is required"}), 400
        if video_title and not video_url:
            resp = requests.get(SEARCH_API_URL, params={"title": video_title}, timeout=15)
            if resp.status_code != 200:
                return jsonify({"error": "Failed to fetch search results"}), 500
            search_result = resp.json()
            if not search_result or 'link' not in search_result:
                return jsonify({"error": "No videos found"}), 404
            video_url = search_result['link']
        if "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)

        cache_key = get_cache_key(video_url)
        json_cache_path = os.path.join(CACHE_JSON_DIR, f"{cache_key}.json")

        # Return cached JSON if it's less than 1 hour old
        if os.path.exists(json_cache_path) and (time.time() - os.path.getmtime(json_cache_path) < 3600):
            with open(json_cache_path, "r") as f:
                cached_data = json.load(f)
            return jsonify(cached_data)

        ydl_opts = {'format': 'worstaudio', 'quiet': True, 'skip_download': True}
        if COOKIE_FILE_PATH:
            ydl_opts['cookiefile'] = COOKIE_FILE_PATH
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            formats = info.get('formats', [])
            audio_format = next((f for f in formats if f.get('acodec') != 'none' and 'url' in f), None)
            if not audio_format:
                return jsonify({"error": "No audio format found"}), 404
            result = {
                "audio": audio_format['url'],
                "cached": True,
                "title": info.get('title', 'Unknown')
            }
            with open(json_cache_path, "w") as f:
                json.dump(result, f)
            return jsonify(result)
    except Exception as e:
        app.logger.error(f"Exception in /down: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return """
    <h1>🎶 YouTube Audio/Video Downloader API</h1>
    <p>Use this API to search and download audio or video from YouTube.</p>
    <ul>
        <li><strong>/search</strong>: ?title=</li>
        <li><strong>/download</strong>: ?url= or ?title=</li>
        <li><strong>/vdown</strong>: ?url= or ?title=</li>
        <li><strong>/down</strong>: ?url= or ?title=</li>
    </ul>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
