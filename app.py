from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests
from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

try:
    import yt_dlp
except Exception:  # pragma: no cover - handled in resolver status
    yt_dlp = None


APP_ROOT = Path(__file__).parent
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", tempfile.gettempdir())) / "twitter-video-download"
CACHE_DIR = DOWNLOAD_DIR / "cache"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RESULT_TTL_SECONDS = int(os.environ.get("RESULT_TTL_SECONDS", "1800"))
MAX_DOWNLOAD_BYTES = int(os.environ.get("MAX_DOWNLOAD_BYTES", str(1024 * 1024 * 1024)))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "20"))
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)


app = Flask(__name__)
RESULT_CACHE: dict[str, dict[str, Any]] = {}


@dataclass
class VideoChoice:
    id: str
    source: str
    url: str
    ext: str = "mp4"
    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    filesize: int | None = None
    note: str = ""

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        if self.height:
            return f"{self.height}p"
        return self.note or "未知分辨率"

    @property
    def label(self) -> str:
        parts = [self.resolution]
        if self.bitrate:
            parts.append(f"{round(self.bitrate / 1000)} kbps")
        parts.append(format_bytes(self.filesize))
        return " · ".join(parts)

    def to_dict(self, result_id: str, base_url: str) -> dict[str, Any]:
        download_path = f"/download/{result_id}/{quote(self.id, safe='')}"
        return {
            "id": self.id,
            "source": self.source,
            "resolution": self.resolution,
            "width": self.width,
            "height": self.height,
            "bitrate": self.bitrate,
            "filesize": self.filesize,
            "size": format_bytes(self.filesize),
            "ext": self.ext,
            "label": self.label,
            "download_url": download_path,
            "absolute_download_url": base_url.rstrip("/") + download_path,
        }

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "url": self.url,
            "ext": self.ext,
            "width": self.width,
            "height": self.height,
            "bitrate": self.bitrate,
            "filesize": self.filesize,
            "note": self.note,
        }

    @classmethod
    def from_cache_dict(cls, data: dict[str, Any]) -> "VideoChoice":
        return cls(
            id=str(data["id"]),
            source=str(data["source"]),
            url=str(data["url"]),
            ext=str(data.get("ext") or "mp4"),
            width=as_int(data.get("width")),
            height=as_int(data.get("height")),
            bitrate=as_int(data.get("bitrate")),
            filesize=as_int(data.get("filesize")),
            note=str(data.get("note") or ""),
        )


@dataclass
class ResolveResult:
    source: str
    title: str = "twitter-video"
    tweet_id: str | None = None
    choices: list[VideoChoice] = field(default_factory=list)


class Resolver:
    name = "resolver"

    def resolve(self, url: str) -> ResolveResult:
        raise NotImplementedError


class YtDlpResolver(Resolver):
    name = "yt-dlp"

    def __init__(self, use_syndication_api: bool = False):
        self.use_syndication_api = use_syndication_api
        if use_syndication_api:
            self.name = "yt-dlp-syndication"

    def resolve(self, url: str) -> ResolveResult:
        if yt_dlp is None:
            raise RuntimeError("yt-dlp 未安装")

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": REQUEST_TIMEOUT,
            "http_headers": {"User-Agent": USER_AGENT},
        }
        if self.use_syndication_api:
            options["extractor_args"] = {"twitter": {"api": ["syndication"]}}

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)

        title = safe_title(info.get("title") or info.get("fulltitle") or "twitter-video")
        tweet_id = str(info.get("id") or extract_tweet_id(url) or "")
        choices = []
        for item in info.get("formats") or []:
            direct_url = item.get("url")
            if not direct_url or not is_http_url(direct_url):
                continue
            if item.get("vcodec") == "none":
                continue
            protocol = (item.get("protocol") or "").lower()
            ext = (item.get("ext") or "mp4").lower()
            if protocol and protocol not in {"http", "https"}:
                continue
            if ext not in {"mp4", "m4v", "mov"}:
                continue
            choice = VideoChoice(
                id=f"{self.name}:{item.get('format_id') or len(choices)}",
                source=self.name,
                url=direct_url,
                ext=ext,
                width=as_int(item.get("width")),
                height=as_int(item.get("height")),
                bitrate=kbps_to_bps(item.get("tbr") or item.get("vbr")),
                filesize=as_int(item.get("filesize") or item.get("filesize_approx")),
                note=item.get("format_note") or item.get("resolution") or "",
            )
            if not choice.filesize:
                choice.filesize = probe_size(choice.url)
            choices.append(choice)

        return ResolveResult(self.name, title=title, tweet_id=tweet_id, choices=normalize_choices(choices))


class GalleryDlResolver(Resolver):
    name = "gallery-dl"

    def resolve(self, url: str) -> ResolveResult:
        cmd = [sys.executable, "-m", "gallery_dl", "-g", "-o", "videos=true", url]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT + 10,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "gallery-dl 解析失败").strip()
            raise RuntimeError(message[-400:])

        raw_urls = [
            line.strip()
            for line in completed.stdout.splitlines()
            if line.strip().startswith("http") and ".mp4" in line
        ]
        choices = []
        for idx, direct_url in enumerate(dict.fromkeys(raw_urls)):
            width, height = resolution_from_url(direct_url)
            choices.append(
                VideoChoice(
                    id=f"{self.name}:{idx}",
                    source=self.name,
                    url=direct_url,
                    ext="mp4",
                    width=width,
                    height=height,
                    filesize=probe_size(direct_url),
                )
            )
        return ResolveResult(self.name, title="twitter-video", tweet_id=extract_tweet_id(url), choices=normalize_choices(choices))


class SyndicationJsonResolver(Resolver):
    name = "direct-syndication-json"

    def resolve(self, url: str) -> ResolveResult:
        tweet_id = extract_tweet_id(url)
        if not tweet_id:
            raise RuntimeError("无法从链接中提取 Tweet ID")

        endpoint = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&lang=zh-cn"
        response = requests.get(endpoint, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()

        title = safe_title(payload.get("text") or f"twitter-{tweet_id}")
        choices = []
        for media in find_media_objects(payload):
            video_info = media.get("video_info") or media.get("videoInfo") or {}
            for variant in video_info.get("variants") or []:
                direct_url = variant.get("url")
                content_type = (variant.get("content_type") or variant.get("contentType") or "").lower()
                if not direct_url or not is_http_url(direct_url):
                    continue
                if "mp4" not in content_type and ".mp4" not in direct_url:
                    continue
                width, height = resolution_from_url(direct_url)
                choices.append(
                    VideoChoice(
                        id=f"{self.name}:{len(choices)}",
                        source=self.name,
                        url=direct_url,
                        ext="mp4",
                        width=width,
                        height=height,
                        bitrate=as_int(variant.get("bitrate")),
                        filesize=probe_size(direct_url),
                    )
                )

        return ResolveResult(self.name, title=title, tweet_id=tweet_id, choices=normalize_choices(choices))


RESOLVERS: list[Resolver] = [
    YtDlpResolver(use_syndication_api=False),
    YtDlpResolver(use_syndication_api=True),
    GalleryDlResolver(),
    SyndicationJsonResolver(),
]


@app.get("/")
def index():
    return render_template("index.html", initial_url=request.args.get("url", ""))


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.errorhandler(HTTPException)
def handle_http_error(exc: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"message": exc.description, "code": exc.code}), exc.code
    return exc


@app.post("/api/parse")
def api_parse():
    payload = request.get_json(silent=True) or {}
    url = (payload.get("url") or request.form.get("url") or "").strip()
    result, attempts = resolve_twitter_url(url)
    result_id = cache_result(result)
    return jsonify(
        {
            "id": result_id,
            "source": result.source,
            "title": result.title,
            "tweet_id": result.tweet_id,
            "attempts": attempts,
            "choices": [choice.to_dict(result_id, request.host_url) for choice in result.choices],
        }
    )


@app.get("/api/shortcut")
def api_shortcut():
    url = (request.args.get("url") or "").strip()
    result, attempts = resolve_twitter_url(url)
    result_id = cache_result(result)
    items = [
        {
            "label": choice.label,
            "download_url": choice.to_dict(result_id, request.host_url)["absolute_download_url"],
            "resolution": choice.resolution,
            "size": format_bytes(choice.filesize),
        }
        for choice in result.choices
    ]
    return jsonify(
        {
            "title": result.title,
            "source": result.source,
            "attempts": attempts,
            "items": items,
            "labels": [item["label"] for item in items],
            "downloads": {item["label"]: item["download_url"] for item in items},
        }
    )


@app.get("/download/<result_id>/<choice_id>")
def download(result_id: str, choice_id: str):
    cleanup_cache()
    cached = load_cached_result(result_id)
    if not cached:
        abort(404, "解析结果已过期，请重新解析")

    choice = next((item for item in cached["choices"] if item.id == choice_id), None)
    if not choice:
        abort(404, "未找到该分辨率")

    filename = safe_title(cached.get("title") or "twitter-video")
    if cached.get("tweet_id"):
        filename = f"{filename}-{cached['tweet_id']}"
    output_path = DOWNLOAD_DIR / f"{result_id}-{safe_title(choice_id)}.{choice.ext}"

    if not output_path.exists():
        stream_remote_file(choice.url, output_path)

    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"{filename}-{choice.resolution}.{choice.ext}",
        mimetype="video/mp4",
        max_age=0,
    )


def resolve_twitter_url(url: str) -> tuple[ResolveResult, list[dict[str, Any]]]:
    cleanup_cache()
    validate_twitter_url(url)
    attempts = []
    errors = []

    for resolver in RESOLVERS:
        started = time.perf_counter()
        try:
            result = resolver.resolve(url)
            elapsed = round((time.perf_counter() - started) * 1000)
            if result.choices:
                attempts.append({"source": resolver.name, "ok": True, "count": len(result.choices), "ms": elapsed})
                return result, attempts
            raise RuntimeError("没有找到可下载的 mp4 视频格式")
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000)
            message = str(exc).strip() or exc.__class__.__name__
            attempts.append({"source": resolver.name, "ok": False, "error": message[-500:], "ms": elapsed})
            errors.append(f"{resolver.name}: {message}")

    abort(422, "所有解析源均失败：" + " | ".join(errors))


def validate_twitter_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    allowed_hosts = {
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "vxtwitter.com",
        "www.vxtwitter.com",
        "fxtwitter.com",
        "www.fxtwitter.com",
    }
    if parsed.scheme not in {"http", "https"} or host not in allowed_hosts:
        abort(400, "请输入有效的 Twitter/X 视频链接")
    if not extract_tweet_id(url):
        abort(400, "链接中没有找到 Tweet ID，请输入单条推文的视频链接")


def cache_result(result: ResolveResult) -> str:
    result_id = uuid.uuid4().hex
    payload = {
        "created_at": time.time(),
        "title": result.title,
        "tweet_id": result.tweet_id,
        "choices": result.choices,
    }
    RESULT_CACHE[result_id] = payload

    disk_payload = {
        **payload,
        "choices": [choice.to_cache_dict() for choice in result.choices],
    }
    cache_path = cache_file_path(result_id)
    tmp_path = cache_path.with_suffix(".json.part")
    tmp_path.write_text(json.dumps(disk_payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(cache_path)
    return result_id


def load_cached_result(result_id: str) -> dict[str, Any] | None:
    cached = RESULT_CACHE.get(result_id)
    if cached and time.time() - cached["created_at"] <= RESULT_TTL_SECONDS:
        return cached

    try:
        cache_path = cache_file_path(result_id)
    except ValueError:
        return None
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if time.time() - payload["created_at"] > RESULT_TTL_SECONDS:
            delete_cached_files(result_id)
            return None
        payload["choices"] = [VideoChoice.from_cache_dict(item) for item in payload.get("choices", [])]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        delete_cached_files(result_id)
        return None

    RESULT_CACHE[result_id] = payload
    return payload


def cleanup_cache() -> None:
    now = time.time()
    expired = [key for key, value in RESULT_CACHE.items() if now - value["created_at"] > RESULT_TTL_SECONDS]
    for key in expired:
        RESULT_CACHE.pop(key, None)
        delete_cached_files(key)

    for cache_path in CACHE_DIR.glob("*.json"):
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if now - payload.get("created_at", 0) > RESULT_TTL_SECONDS:
                delete_cached_files(cache_path.stem)
        except (OSError, json.JSONDecodeError):
            delete_cached_files(cache_path.stem)


def cache_file_path(result_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", result_id):
        raise ValueError("invalid result id")
    return CACHE_DIR / f"{result_id}.json"


def delete_cached_files(result_id: str) -> None:
    try:
        paths = [cache_file_path(result_id), *DOWNLOAD_DIR.glob(f"{result_id}-*")]
    except ValueError:
        return
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def stream_remote_file(url: str, destination: Path) -> None:
    with requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=REQUEST_TIMEOUT) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        if total > MAX_DOWNLOAD_BYTES:
            abort(413, "视频文件超过服务端限制")

        downloaded = 0
        tmp_path = destination.with_suffix(destination.suffix + ".part")
        with tmp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    tmp_path.unlink(missing_ok=True)
                    abort(413, "视频文件超过服务端限制")
                handle.write(chunk)
        tmp_path.replace(destination)


def normalize_choices(choices: list[VideoChoice]) -> list[VideoChoice]:
    unique: dict[tuple[Any, ...], VideoChoice] = {}
    for choice in choices:
        key = (choice.width, choice.height, choice.bitrate, choice.url.split("?")[0])
        if key not in unique:
            unique[key] = choice

    normalized = list(unique.values())
    normalized.sort(key=lambda item: (item.height or 0, item.width or 0, item.bitrate or 0), reverse=True)
    for index, choice in enumerate(normalized):
        choice.id = f"{choice.source}:{index}"
    return normalized


def find_media_objects(value: Any) -> list[dict[str, Any]]:
    found = []
    if isinstance(value, dict):
        if value.get("video_info") or value.get("videoInfo"):
            found.append(value)
        for child in value.values():
            found.extend(find_media_objects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_media_objects(child))
    return found


def extract_tweet_id(url: str) -> str | None:
    patterns = [
        r"/status(?:es)?/(\d+)",
        r"/i/web/status/(\d+)",
        r"[?&]id=(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def resolution_from_url(url: str) -> tuple[int | None, int | None]:
    match = re.search(r"/vid/(\d+)x(\d+)/", url)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(?<!\d)(\d{3,4})x(\d{3,4})(?!\d)", url)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def probe_size(url: str) -> int | None:
    try:
        response = requests.head(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
            allow_redirects=True,
            timeout=8,
        )
        if response.ok and response.headers.get("Content-Length"):
            return int(response.headers["Content-Length"])
    except Exception:
        pass
    return None


def format_bytes(size: int | None) -> str:
    if not size:
        return "大小未知"
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def safe_title(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", text, flags=re.UNICODE).strip("-")
    return text[:90] or "twitter-video"


def as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def kbps_to_bps(value: Any) -> int | None:
    number = as_int(value)
    return number * 1000 if number else None


def is_http_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


@atexit.register
def remove_old_files() -> None:
    for path in [*DOWNLOAD_DIR.glob("*"), *CACHE_DIR.glob("*")]:
        try:
            if path.is_file() and time.time() - path.stat().st_mtime > RESULT_TTL_SECONDS:
                path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
