"""Team logos taken from the matches page, cached on disk, pruned by age."""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

log = logging.getLogger("hltv_bot.team_logos")

CACHE_DIR = Path("data/team_logos")
TEAM_LOGO_MAX_AGE_SEC = 90 * 24 * 3600
EVENT_LOGO_MAX_AGE_SEC = 7 * 24 * 3600
MAX_AGE_SEC = TEAM_LOGO_MAX_AGE_SEC
_MAX_BYTES = 1_500_000

_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
_EXT = {
    "png": ".png",
    "jpg": ".jpg",
    "gif": ".gif",
    "webp": ".webp",
    "svg": ".svg",
}


def logo_cache_key(url: str) -> str:
    parts = urlsplit((url or "").strip())
    ident = (parts.netloc + parts.path).lower()
    return hashlib.sha1(ident.encode()).hexdigest()[:20]


def _find_cached(key: str) -> Path | None:
    return find_cached_stem(CACHE_DIR, key)


def cached_data_uri(url: str) -> str:
    """Return a data URI for a cached logo. Touches the file so prune keeps it."""
    path = _find_cached(logo_cache_key(url))
    if path is None:
        return ""
    return data_uri_for(path)


def prune_image_dir(directory: Path, max_age: float = TEAM_LOGO_MAX_AGE_SEC) -> int:
    """Delete cached images in directory that have not been used within max_age."""
    if not directory.exists():
        return 0
    now = time.time()
    removed = 0
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in _MIME:
            continue
        try:
            if now - path.stat().st_mtime > max_age:
                path.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        log.info("image cache pruned dir=%s n=%s", directory, removed)
    return removed


def prune_team_logos(max_age: float = TEAM_LOGO_MAX_AGE_SEC) -> int:
    """Delete team logos unused for max_age (default 90 days)."""
    return prune_image_dir(CACHE_DIR, max_age)


def find_cached_stem(directory: Path, stem: str) -> Path | None:
    if not stem or not directory.exists():
        return None
    for ext in _MIME:
        path = directory / f"{stem}{ext}"
        try:
            if path.is_file() and path.stat().st_size > 40:
                return path
        except OSError:
            continue
    return None


def data_uri_for(path: Path) -> str:
    """Read an image file as a data URI and touch it so prune keeps it."""
    mime = _MIME.get(path.suffix.lower(), "")
    if not mime:
        return ""
    try:
        data = path.read_bytes()
        path.touch()
    except OSError:
        return ""
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def save_image(directory: Path, stem: str, data: bytes) -> Path | None:
    kind = _sniff(data)
    if not kind or not stem:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{stem}{_EXT[kind]}"
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
    except OSError as e:
        log.debug("image save failed stem=%s: %s", stem, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return dest


_FETCH_WORKERS = 8
_CHROME_BATCH = 40


def download_images(urls: list[str]) -> dict[str, bytes]:
    """Fetch every URL. Plain GET runs in parallel; non-images fall through to Chrome."""
    return _download_many(urls)


def ensure_team_logos(urls: list[str]) -> None:
    """Download logos missing from disk. Prunes stale files first."""
    prune_team_logos()
    missing: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        url = (raw or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        path = _find_cached(logo_cache_key(url))
        if path is not None:
            try:
                path.touch()
            except OSError:
                pass
            continue
        missing.append(url)
    if not missing:
        return
    fetched = download_images(missing)
    for url, data in fetched.items():
        if save_image(CACHE_DIR, logo_cache_key(url), data) is None:
            log.debug("team logo not an image url=%s bytes=%s", url, len(data))


def _sniff(data: bytes) -> str | None:
    if len(data) < 40:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    head = data[:300].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "svg"
    return None


def _urllib_get(url: str, timeout: float = 8.0) -> bytes | None:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                return None
            return resp.read(_MAX_BYTES)
    except Exception as e:
        log.debug("team logo http failed url=%s: %s", url, e)
        return None


def _as_image(data: bytes | None) -> bytes | None:
    if not data or _sniff(data) is None:
        return None
    return data


def _download_many(urls: list[str]) -> dict[str, bytes]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            unique.append(url)
    out: dict[str, bytes] = {}
    failed: list[str] = []
    if not unique:
        return out
    workers = min(_FETCH_WORKERS, len(unique))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_urllib_get, url): url for url in unique}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                data = _as_image(fut.result())
            except Exception as e:
                log.debug("team logo fetch failed url=%s: %s", url, e)
                data = None
            if data:
                out[url] = data
            else:
                failed.append(url)
    for start in range(0, len(failed), _CHROME_BATCH):
        batch = failed[start : start + _CHROME_BATCH]
        for url, data in _chrome_batch(batch).items():
            img = _as_image(data)
            if img:
                out[url] = img
    return out


def _chrome_batch(urls: list[str], timeout: float = 20.0) -> dict[str, bytes]:
    """Fetch images inside the keeper tab. Used when a plain GET is blocked."""
    try:
        import json

        from hltv_bot.cdp import DEFAULT_CDP, _connect_ws, _list_pages, _pick_keeper_page
    except Exception as e:
        log.debug("team logo chrome import failed: %s", e)
        return {}
    try:
        pages = _list_pages(DEFAULT_CDP, min(timeout, 3.0))
        page = _pick_keeper_page(pages)
        if not page or not page.get("webSocketDebuggerUrl"):
            return {}
        client = _connect_ws(str(page["webSocketDebuggerUrl"]), timeout)
    except Exception as e:
        log.debug("team logo chrome attach failed: %s", e)
        return {}
    js = """(async () => {
      const urls = %s;
      const out = {};
      await Promise.all(urls.map(async (u) => {
        try {
          const res = await fetch(u, {credentials: "include", redirect: "follow"});
          if (!res.ok) return;
          const buf = new Uint8Array(await res.arrayBuffer());
          if (buf.length < 40 || buf.length > %s) return;
          let bin = "";
          const step = 0x8000;
          for (let i = 0; i < buf.length; i += step) {
            bin += String.fromCharCode.apply(null, buf.subarray(i, i + step));
          }
          out[u] = btoa(bin);
        } catch (e) {}
      }));
      return out;
    })()""" % (json.dumps(urls), _MAX_BYTES)
    try:
        try:
            client.call("Runtime.enable", timeout=min(timeout, 3.0))
        except Exception:
            pass
        res = client.call(
            "Runtime.evaluate",
            {"expression": js, "awaitPromise": True, "returnByValue": True},
            timeout=timeout,
        )
        val = res.get("result", {}).get("value") if isinstance(res, dict) else None
        if not isinstance(val, dict):
            return {}
        decoded: dict[str, bytes] = {}
        for url, b64 in val.items():
            if not isinstance(b64, str) or not b64:
                continue
            try:
                decoded[str(url)] = base64.b64decode(b64)
            except Exception:
                continue
        return decoded
    except Exception as e:
        log.debug("team logo chrome batch failed: %s", e)
        return {}
    finally:
        try:
            client.ws.close()
        except Exception:
            pass
