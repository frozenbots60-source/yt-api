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
import platform
import zipfile
import sys

# --- EJS FIX: Initialize Deno + yt-dlp challenge solver ---
TEMP_DIR = os.path.abspath("./temp")
DENO_DIR = os.path.join(TEMP_DIR, "deno")
DENO_EXE = os.path.join(DENO_DIR, "deno.exe")


def ensure_deno():
    if os.path.exists(DENO_EXE):
        return DENO_EXE

    if platform.system().lower() != "windows":
        raise RuntimeError("Auto Deno download implemented only for Windows")

    os.makedirs(DENO_DIR, exist_ok=True)

    print("[INIT] Deno not found. Downloading...")

    deno_url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
    zip_path = os.path.join(TEMP_DIR, "deno.zip")

    with requests.get(deno_url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(DENO_DIR)

    os.remove(zip_path)

    if not os.path.exists(DENO_EXE):
        raise RuntimeError("Deno download failed")

    print("[INIT] Deno downloaded successfully.")
    return DENO_EXE


def ensure_impersonation_backend():
    """
    Ensure curl-cffi (impersonation backend) is available. Attempt to install it via pip if missing.
    This helps yt-dlp perform browser impersonation (required for Kick on Linux/Heroku).
    """
    try:
        import curl_cffi  # type: ignore
        print("[INIT] curl-cffi already installed")
        return
    except Exception:
        pass

    print("[INIT] curl-cffi not found. Installing via pip...")

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "curl-cffi>=0.6.0"],
            check=True,
        )
        print("[INIT] curl-cffi installed successfully")
    except Exception as e:
        print(f"[INIT ERROR] Failed to install curl-cffi: {e}")


def init_yt_dlp_solver():
    try:
        # Ensure impersonation backend (curl-cffi) is present on Linux environments
        try:
            ensure_impersonation_backend()
        except Exception as ie:
            print(f"[INIT WARNING] ensure_impersonation_backend failed: {ie}")

        deno_path = None
        try:
            deno_path = ensure_deno()
        except Exception as de:
            # keep behavior consistent with previous runs: print and continue
            print(f"[INIT ERROR] {de}")

        # If Deno was downloaded / found, add it to PATH for the subprocess calls below
        env = os.environ.copy()
        if deno_path:
            env["PATH"] = DENO_DIR + os.pathsep + env.get("PATH", "")

        # Clear old caches only (NO NIGHTLY UPDATES ANYMORE)
        try:
            subprocess.run(["yt-dlp", "--rm-cache-dir"], check=False, env=env)
        except Exception as e:
            print(f"[INIT WARNING] Failed to run yt-dlp --rm-cache-dir: {e}")

        # Preload EJS challenge solver (best-effort)
        try:
            subprocess.run(
                [
                    "yt-dlp",
                    "--remote-components",
                    "ejs:github",
                    "--simulate",
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                ],
                check=False,
                env=env,
            )
            print("[INIT] yt-dlp EJS challenge solver initialized successfully.")
        except Exception as e:
            print(f"[INIT WARNING] Failed to preload EJS solver: {e}")

    except Exception as e:
        print(f"[INIT ERROR] Failed to initialize yt-dlp EJS solver: {e}")


threading.Thread(target=init_yt_dlp_solver, daemon=True).start()

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
def is_kick_url(url: str) -> bool:
    return "kick.com/" in url.lower()

def make_ydl_opts_kick():
    opts = {
        "quiet": True,
        "skip_download": True,
        "format": "best",
    }
    if COOKIE_FILE_PATH:
        opts["cookiefile"] = COOKIE_FILE_PATH
    return opts

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
    total_size = get_directory_size(CACHE_DIR) + get_directory_size(CACHE_VIDEO_DIR)
    if total_size > MAX_CACHE_SIZE:
        app.logger.info(f"Cache size {total_size} exceeds {MAX_CACHE_SIZE}, clearing caches.")
        for cache_dir in [CACHE_DIR, CACHE_VIDEO_DIR]:
            for file in os.listdir(cache_dir):
                try:
                    os.remove(os.path.join(cache_dir, file))
                except Exception:
                    pass

def periodic_cache_cleanup():
    while True:
        check_cache_size_and_cleanup()
        time.sleep(60)

threading.Thread(target=periodic_cache_cleanup, daemon=True).start()

def resolve_spotify_link(url: str) -> str:
    if "spotify.com" in url:
        resp = requests.get(SEARCH_API_URL, params={"title": url}, timeout=15)
        if resp.status_code != 200:
            raise Exception("Failed to fetch search results for Spotify")
        result = resp.json()
        if not result or "link" not in result:
            raise Exception("No YouTube result for Spotify")
        return result["link"]
    return url

def make_ydl_opts_audio(output_template: str):
    opts = {
        'format': '249',
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

def make_ydl_opts_video(output_template: str):
    opts = {
        'format': 'best[ext=mp4][vcodec^=avc1][acodec^=mp4a][height<=360]/best[ext=mp4]/best',
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
    cached_files = glob.glob(os.path.join(CACHE_DIR, f"{cache_key}.webm"))
    if cached_files:
        return cached_files[0]

    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")

    with yt_dlp.YoutubeDL(make_ydl_opts_audio(output_template)) as ydl:
        info = ydl.extract_info(video_url, download=True)
        downloaded_file = ydl.prepare_filename(info)

        # Move to cache with .webm extension (locked itag 249 -> webm)
        cached_file_path = os.path.join(CACHE_DIR, f"{cache_key}.webm")
        try:
            shutil.move(downloaded_file, cached_file_path)
        except Exception:
            # If prepare_filename didn't point to final file (edge-cases), fallback to glob
            candidates = glob.glob(os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.*"))
            if not candidates:
                raise Exception("Audio download failed: no file produced")
            downloaded_file = candidates[0]
            shutil.move(downloaded_file, cached_file_path)

        check_cache_size_and_cleanup()
        return cached_file_path

def download_video(video_url: str) -> str:
    """
    Downloads the best video + best audio, merges into mp4 when necessary,
    caches the result as {cache_key}.mp4 and returns the cached file path.
    """
    cache_key = hashlib.md5((video_url + "_video").encode()).hexdigest()
    cached_files = glob.glob(os.path.join(CACHE_VIDEO_DIR, f"{cache_key}.mp4"))
    if cached_files:
        return cached_files[0]

    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")

    opts = make_ydl_opts_video(output_template)
    # Force merge to mp4 if merging is required
    opts['merge_output_format'] = 'mp4'
    # Make sure we are not writing to cache dir directly to avoid partial files there
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url, download=True)

    # After download, find produced file(s)
    candidates = glob.glob(os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.*"))
    if not candidates:
        # As a fallback, attempt to use ydl.prepare_filename(info) if available
        try:
            downloaded_file = ydl.prepare_filename(info)
        except Exception:
            raise Exception("Video download failed: no file produced")
    else:
        # Prefer mp4 final merged file if present
        mp4_candidate = next((c for c in candidates if c.lower().endswith('.mp4')), None)
        downloaded_file = mp4_candidate or candidates[0]

    # Ensure final cache file path ends with .mp4
    cached_file_path = os.path.join(CACHE_VIDEO_DIR, f"{cache_key}.mp4")
    try:
        shutil.move(downloaded_file, cached_file_path)
    except Exception:
        # If moving fails, try copying then removing
        shutil.copy2(downloaded_file, cached_file_path)
        try:
            os.remove(downloaded_file)
        except Exception:
            pass

    # Cleanup any remaining temp candidates for this unique_id
    for c in glob.glob(os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.*")):
        try:
            os.remove(c)
        except Exception:
            pass

    check_cache_size_and_cleanup()
    return cached_file_path

# --- Endpoints ---

@app.route('/search', methods=['GET'])
def search_video():
    try:
        query = request.args.get('title')
        if not query:
            return jsonify({"error": "The 'title' parameter is required"}), 400

        resp = requests.get(SEARCH_API_URL, params={"title": query}, timeout=15)
        if resp.status_code != 200:
            return jsonify({"error": "Search API failure"}), 500

        result = resp.json()
        if not result or "link" not in result:
            return jsonify({"error": "No results"}), 404

        video_url = result["link"]
        threading.Thread(target=download_audio, args=(video_url,), daemon=True).start()
        threading.Thread(target=download_video, args=(video_url,), daemon=True).start()

        return jsonify({
            "title": result.get("title"),
            "url": video_url,
            "duration": result.get("duration"),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/vdown', methods=['GET'])
def download_video_endpoint():
    try:
        video_url = request.args.get('url')
        video_title = request.args.get('title')

        if video_title and not video_url:
            resp = requests.get(SEARCH_API_URL, params={"title": video_title}, timeout=15)
            if resp.status_code != 200:
                return jsonify({"error": "Search API error"}), 500
            video_url = resp.json()["link"]

        if "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)

        cached_file_path = download_video(video_url)
        return send_file(cached_file_path, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download', methods=['GET'])
def download_audio_endpoint():
    try:
        video_url = request.args.get('url')
        video_title = request.args.get('title')

        if video_title and not video_url:
            resp = requests.get(SEARCH_API_URL, params={"title": video_title}, timeout=15)
            if resp.status_code != 200:
                return jsonify({"error": "Search API error"}), 500
            video_url = resp.json()["link"]

        if "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)

        cached_file_path = download_audio(video_url)
        return send_file(cached_file_path, as_attachment=True)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- CDN ONLY ENDPOINT (LOCKED TO ITAG 249 WEBM OR KICK HLS) ---
@app.route('/down', methods=['GET'])
def get_cdn_link():
    try:
        video_url = request.args.get('url')
        video_title = request.args.get('title')

        if video_title and not video_url:
            resp = requests.get(SEARCH_API_URL, params={"title": video_title}, timeout=15)
            video_url = resp.json()["link"]

        if "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)

        # ---- KICK PATH ----
        if is_kick_url(video_url):
            with yt_dlp.YoutubeDL(make_ydl_opts_kick()) as ydl:
                info = ydl.extract_info(video_url, download=False)

                hls_url = info.get("url")
                if not hls_url:
                    return jsonify({"error": "No HLS stream found"}), 404

                return jsonify({
                    "type": "kick",
                    "stream": hls_url,
                    "title": info.get("title"),
                    "is_live": info.get("is_live", True)
                })

        # ---- YOUTUBE PATH ----
        cache_key = get_cache_key(video_url)
        cached = bool(glob.glob(os.path.join(CACHE_DIR, f"{cache_key}.webm")))

        opts = {
            'format': '249',
            'skip_download': True,
            'quiet': True,
        }
        if COOKIE_FILE_PATH:
            opts['cookiefile'] = COOKIE_FILE_PATH

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            formats = info.get("formats", [])

            fmt_249 = next((f for f in formats if str(f.get('format_id')) == "249"), None)
            if not fmt_249 or "url" not in fmt_249:
                return jsonify({"error": "itag 249 not available"}), 404

            return jsonify({
                "type": "youtube",
                "audio": fmt_249["url"],
                "cached": cached,
                "title": info.get("title")
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return """
    <h1>🎶 YouTube Audio/Video Downloader API</h1>
    <p><strong>Low-bitrate locked API (itag 249)</strong></p>
    <ul>
        <li>/search?title=</li>
        <li>/download?url=</li>
        <li>/vdown?url=</li>
        <li>/down?url=</li>
    </ul>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
