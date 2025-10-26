from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import uuid
import requests
import shutil
import subprocess
import logging

app = Flask(__name__)

# --- Configuration ---
BASE_TEMP_DIR = "/tmp"
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

TEMP_DOWNLOAD_DIR = os.path.join(BASE_TEMP_DIR, "download")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

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
    ffmpeg_path = shutil.which("ffmpeg")
    opts = {
        'format': 'bestaudio[ext=webm]/bestaudio/best',
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'n_threads': 4,
        'concurrent_fragment_downloads': 4,
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def make_ydl_opts_video(output_template: str):
    opts = {
        'format': 'worstvideo[ext=mp4]+worstaudio/best',
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'n_threads': 4,
        'concurrent_fragment_downloads': 4,
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def download_audio(video_url: str) -> str:
    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    ydl_opts = make_ydl_opts_audio(output_template)

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise Exception("ffmpeg not found in PATH — install ffmpeg or add it to PATH")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        downloaded_file = ydl.prepare_filename(info)

        # Skip conversion if already opus/webm
        if downloaded_file.endswith(".webm") or downloaded_file.endswith(".opus"):
            return downloaded_file

        temp_audio_path = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.opus")
        ffmpeg_cmd = [
            ffmpeg_path,
            "-y",
            "-i", downloaded_file,
            "-vn",
            "-c:a", "libopus",
            "-b:a", "48k",
            "-vbr", "on",
            "-application", "audio",
            "-threads", "0",
            temp_audio_path
        ]
        completed = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if completed.returncode != 0:
            raise Exception(f"ffmpeg failed: {completed.stderr.decode('utf-8', errors='ignore')}")

        try:
            os.remove(downloaded_file)
        except Exception:
            pass

        return temp_audio_path

def download_video(video_url: str) -> str:
    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    ydl_opts = make_ydl_opts_video(output_template)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=True)
        downloaded_file = ydl.prepare_filename(info)
        if not os.path.isfile(downloaded_file):
            matches = [f for f in os.listdir(TEMP_DOWNLOAD_DIR) if f.startswith(unique_id)]
            if matches:
                downloaded_file = os.path.join(TEMP_DOWNLOAD_DIR, matches[0])
            else:
                raise Exception("Downloaded video file not found")
        return downloaded_file

# --- Endpoints ---
@app.route('/search', methods=['GET'])
def search_video():
    try:
        query = request.args.get('title')
        if not query:
            return jsonify({"error": "The 'title' parameter is required"}), 400
        resp = requests.get(SEARCH_API_URL, params={"title": query}, timeout=15)
        if resp.status_code != 200:
            return jsonify({"error": "Failed to fetch search results"}), 500
        search_result = resp.json()
        if not search_result or 'link' not in search_result:
            return jsonify({"error": "No videos found for the given query"}), 404
        video_url = search_result['link']
        return jsonify({
            "title": search_result.get("title"),
            "url": video_url,
            "duration": search_result.get("duration"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/vdown', methods=['GET'])
def download_video_endpoint():
    temp_files = []
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
                return jsonify({"error": "No videos found for the given query"}), 404
            video_url = search_result['link']
        if video_url and "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)
        temp_file = download_video(video_url)
        temp_files.append(temp_file)
        return send_file(
            temp_file,
            as_attachment=True,
            download_name=os.path.basename(temp_file)
        )
    finally:
        for f in temp_files:
            try:
                os.remove(f)
            except Exception:
                pass

@app.route('/download', methods=['GET'])
def download_audio_endpoint():
    temp_files = []
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
                return jsonify({"error": "No videos found for the given query"}), 404
            video_url = search_result['link']
        if video_url and "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)
        temp_file = download_audio(video_url)
        temp_files.append(temp_file)
        return send_file(
            temp_file,
            as_attachment=True,
            download_name=os.path.basename(temp_file)
        )
    finally:
        for f in temp_files:
            try:
                os.remove(f)
            except Exception:
                pass

@app.route('/')
def home():
    return """
    <h1>🎶 YouTube Audio/Video Downloader API</h1>
    <p>Use this API to search and download audio or video from YouTube.</p>
    <p><strong>Endpoints:</strong></p>
    <ul>
        <li><strong>/search</strong>: Search for a video by title. Query param: <code>?title=</code></li>
        <li><strong>/download</strong>: Download audio by URL or search by title. Query params: <code>?url=</code> or <code>?title=</code></li>
        <li><strong>/vdown</strong>: Download video by URL or search by title. Query params: <code>?url=</code> or <code>?title=</code></li>
    </ul>
    <p>Example:</p>
    <pre>/download?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ</pre>
    """

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

