from flask import Flask, request, jsonify, Response
import yt_dlp
import os
import requests
import shutil
import logging

app = Flask(__name__)

# --- Configuration ---
BASE_TEMP_DIR = "/tmp"
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

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

def make_ydl_opts_audio():
    opts = {
        'format': 'bestaudio[ext=webm]/bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'n_threads': 8,
        'concurrent_fragment_downloads': 8,
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def make_ydl_opts_video():
    opts = {
        'format': 'worstvideo[ext=mp4]+worstaudio/best',
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'n_threads': 8,
        'concurrent_fragment_downloads': 8,
    }
    if COOKIE_FILE_PATH:
        opts['cookiefile'] = COOKIE_FILE_PATH
    return opts

def stream_yt(url, ydl_opts):
    """
    Generator to stream audio/video directly from yt-dlp
    """
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [info])
        for fmt in formats:
            if fmt.get('url'):
                stream_url = fmt['url']
                break
        else:
            raise Exception("No downloadable format found")
        # stream directly
        resp = requests.get(stream_url, stream=True, timeout=60)
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

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
        ydl_opts = make_ydl_opts_video()
        return Response(
            stream_yt(video_url, ydl_opts),
            mimetype='video/mp4',
            headers={"Content-Disposition": f"attachment; filename=video.mp4"}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
                return jsonify({"error": "No videos found for the given query"}), 404
            video_url = search_result['link']
        if video_url and "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)
        ydl_opts = make_ydl_opts_audio()
        return Response(
            stream_yt(video_url, ydl_opts),
            mimetype='audio/ogg',
            headers={"Content-Disposition": f"attachment; filename=audio.opus"}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
