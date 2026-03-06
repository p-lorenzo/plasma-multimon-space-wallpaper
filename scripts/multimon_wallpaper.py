#!/usr/bin/env python3
"""Fetch NASA images and generate per-monitor wallpapers for Plasma 6."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - dependency error path
    raise SystemExit("Pillow is required: pip install pillow") from exc

APP_NAME = "plasma-multimon-space-wallpaper"


@dataclass
class Monitor:
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0


def default_cache_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return pathlib.Path(base) / APP_NAME


def resolve_cache_dir(path_arg: str) -> pathlib.Path:
    if path_arg.strip():
        return pathlib.Path(os.path.expanduser(path_arg)).resolve()
    return default_cache_dir().resolve()


def load_json(path: pathlib.Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.warning("Invalid cached JSON at %s; ignoring", path)
        return default


def save_json(path: pathlib.Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_xrandr() -> List[Monitor]:
    try:
        result = subprocess.run(["xrandr", "--query"], check=True, text=True, capture_output=True)
    except Exception as exc:
        logging.warning("xrandr unavailable (%s); no monitors detected", exc)
        return []

    monitors: List[Monitor] = []
    rx = re.compile(r"^(?P<name>\S+) connected(?: primary)? (?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+)")
    for line in result.stdout.splitlines():
        m = rx.match(line)
        if not m:
            continue
        monitors.append(
            Monitor(
                name=m.group("name"),
                x=int(m.group("x")),
                y=int(m.group("y")),
                width=int(m.group("w")),
                height=int(m.group("h")),
                scale=1.0,
            )
        )
    return monitors


def http_get_json(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def download_binary(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def image_meets_size(path: pathlib.Path, min_width: int, min_height: int) -> bool:
    with Image.open(path) as img:
        w, h = img.size
    return w >= min_width and h >= min_height


def is_cached_state_usable(state: dict, provider: str, min_width: int, min_height: int) -> bool:
    image_path = pathlib.Path(state.get("image_path", ""))
    if state.get("provider") != provider or not image_path.exists():
        return False
    try:
        return image_meets_size(image_path, min_width, min_height)
    except Exception:
        return False


def fetch_apod_image(
    api_key: str,
    cache_dir: pathlib.Path,
    min_width: int,
    min_height: int,
    lookback_days: int,
) -> Tuple[pathlib.Path, dict]:
    images_dir = cache_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    today = dt.date.today()
    errors: List[str] = []

    for day_offset in range(lookback_days + 1):
        date_str = (today - dt.timedelta(days=day_offset)).isoformat()
        query = urllib.parse.urlencode({"api_key": api_key, "date": date_str, "thumbs": "false"})
        url = f"https://api.nasa.gov/planetary/apod?{query}"
        logging.debug("Fetching APOD metadata for %s", date_str)

        try:
            metadata = http_get_json(url)
        except Exception as exc:
            errors.append(f"{date_str}: metadata error {exc}")
            continue

        if metadata.get("media_type") != "image":
            errors.append(f"{date_str}: not an image entry")
            continue

        image_url = metadata.get("hdurl") or metadata.get("url")
        if not image_url:
            errors.append(f"{date_str}: no image URL")
            continue

        ext = pathlib.Path(urllib.parse.urlparse(image_url).path).suffix.lower() or ".jpg"
        image_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", metadata.get("date") or date_str)
        image_path = images_dir / f"apod_{image_id}{ext}"

        try:
            if not image_path.exists():
                image_path.write_bytes(download_binary(image_url, timeout=60))
            if image_meets_size(image_path, min_width, min_height):
                return image_path, metadata
            errors.append(f"{date_str}: too small ({image_path})")
        except Exception as exc:
            errors.append(f"{date_str}: download/size error {exc}")

    raise RuntimeError(
        "APOD did not return a suitable image above minimum dimensions "
        f"{min_width}x{min_height} in the last {lookback_days} days. Last errors: {errors[:4]}"
    )


def fetch_epic_image(api_key: str, cache_dir: pathlib.Path, min_width: int, min_height: int) -> Tuple[pathlib.Path, dict]:
    images_dir = cache_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    list_url = f"https://api.nasa.gov/EPIC/api/natural/images?{urllib.parse.urlencode({'api_key': api_key})}"
    try:
        items = http_get_json(list_url)
    except Exception as exc:
        raise RuntimeError(f"EPIC API unavailable: {exc}") from exc

    if not isinstance(items, list) or not items:
        raise RuntimeError("EPIC API returned no images")

    for item in items:
        image_name = item.get("image")
        date_str = item.get("date", "")
        if not image_name or not date_str:
            continue

        day = date_str.split(" ")[0]
        try:
            y, m, d = day.split("-")
        except ValueError:
            continue

        image_url = (
            f"https://api.nasa.gov/EPIC/archive/natural/{y}/{m}/{d}/png/{image_name}.png?"
            f"{urllib.parse.urlencode({'api_key': api_key})}"
        )
        image_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"epic_{day}_{image_name}")
        image_path = images_dir / f"{image_id}.png"

        try:
            if not image_path.exists():
                image_path.write_bytes(download_binary(image_url, timeout=60))
            if image_meets_size(image_path, min_width, min_height):
                return image_path, {"provider": "epic", "source": item, "image_url": image_url}
        except Exception:
            continue

    raise RuntimeError(
        "EPIC did not return a suitable image above minimum dimensions "
        f"{min_width}x{min_height}."
    )


def fetch_nasa_library_image(
    cache_dir: pathlib.Path,
    min_width: int,
    min_height: int,
    query: str,
    max_candidates: int = 15,
) -> Tuple[pathlib.Path, dict]:
    """Fetch from NASA Image and Video Library and keep only large still images.

    API docs: https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf
    """
    images_dir = cache_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    search_query = urllib.parse.urlencode(
        {
            "q": query,
            "media_type": "image",
            "page": 1,
            # Avoid too many results while still having enough candidates.
            "page_size": max(25, max_candidates * 3),
        }
    )
    search_url = f"https://images-api.nasa.gov/search?{search_query}"
    logging.debug("Fetching NASA Image Library search: %s", search_url)

    try:
        payload = http_get_json(search_url)
    except Exception as exc:
        raise RuntimeError(f"NASA Image Library API unavailable: {exc}") from exc

    items = payload.get("collection", {}).get("items", [])
    if not items:
        raise RuntimeError("NASA Image Library returned no search results")

    candidates_checked = 0
    errors: List[str] = []

    for item in items:
        data = (item.get("data") or [{}])[0]
        links = item.get("links") or []
        if not links:
            continue

        thumb = links[0].get("href", "")
        nasa_id = data.get("nasa_id")
        if not nasa_id:
            continue

        asset_url = f"https://images-api.nasa.gov/asset/{urllib.parse.quote(nasa_id)}.json"
        try:
            asset_payload = http_get_json(asset_url)
            asset_items = asset_payload.get("collection", {}).get("items", [])
        except Exception as exc:
            errors.append(f"{nasa_id}: asset fetch error {exc}")
            continue

        # Prefer the highest quality image URL from asset list.
        preferred: Optional[str] = None
        for a in reversed(asset_items):
            href = a.get("href", "")
            if re.search(r"\.(jpg|jpeg|png|tif|tiff)$", href, re.IGNORECASE):
                preferred = href
                break
        if not preferred and thumb:
            preferred = thumb
        if not preferred:
            continue

        ext = pathlib.Path(urllib.parse.urlparse(preferred).path).suffix.lower() or ".jpg"
        file_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"library_{nasa_id}")
        image_path = images_dir / f"{file_id}{ext}"

        try:
            if not image_path.exists():
                image_path.write_bytes(download_binary(preferred, timeout=60))
            if image_meets_size(image_path, min_width, min_height):
                return image_path, {
                    "provider": "library",
                    "query": query,
                    "nasa_id": nasa_id,
                    "title": data.get("title"),
                    "description": data.get("description"),
                    "image_url": preferred,
                    "asset_url": asset_url,
                }
            errors.append(f"{nasa_id}: too small ({image_path})")
        except Exception as exc:
            errors.append(f"{nasa_id}: download/size error {exc}")

        candidates_checked += 1
        if candidates_checked >= max_candidates:
            break

    raise RuntimeError(
        "NASA Image Library did not return a suitable image above minimum dimensions "
        f"{min_width}x{min_height} for query '{query}'. Last errors: {errors[:4]}"
    )


def fetch_nasa_image(
    provider: str,
    api_key: str,
    cache_dir: pathlib.Path,
    min_width: int,
    min_height: int,
    lookback_days: int,
    library_query: str,
    force: bool = False,
) -> Tuple[pathlib.Path, dict]:
    state_path = cache_dir / "state" / "last_fetch.json"
    state = load_json(state_path, default={})

    if not force and is_cached_state_usable(state, provider, min_width, min_height):
        logging.info("Reusing cached %s image: %s", provider, state["image_path"])
        return pathlib.Path(state["image_path"]), state.get("metadata", {})

    if provider == "apod":
        image_path, metadata = fetch_apod_image(api_key, cache_dir, min_width, min_height, lookback_days)
    elif provider == "epic":
        image_path, metadata = fetch_epic_image(api_key, cache_dir, min_width, min_height)
    elif provider == "library":
        image_path, metadata = fetch_nasa_library_image(cache_dir, min_width, min_height, library_query)
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")

    save_json(
        state_path,
        {
            "provider": provider,
            "image_path": str(image_path),
            "fetched_at": int(time.time()),
            "min_width": min_width,
            "min_height": min_height,
            "metadata": metadata,
        },
    )
    return image_path, metadata


def compute_virtual_canvas(monitors: List[Monitor]) -> Tuple[int, int, int, int]:
    min_x = min(m.x for m in monitors)
    min_y = min(m.y for m in monitors)
    max_x = max(m.x + m.width for m in monitors)
    max_y = max(m.y + m.height for m in monitors)
    return min_x, min_y, max_x - min_x, max_y - min_y


def fit_cover(src_w: int, src_h: int, dst_w: int, dst_h: int) -> Tuple[int, int]:
    ratio = max(dst_w / src_w, dst_h / src_h)
    return int(src_w * ratio), int(src_h * ratio)


def fit_contain(src_w: int, src_h: int, dst_w: int, dst_h: int) -> Tuple[int, int]:
    ratio = min(dst_w / src_w, dst_h / src_h)
    return int(src_w * ratio), int(src_h * ratio)


def render_virtual_canvas(
    image_path: pathlib.Path,
    canvas_size: Tuple[int, int],
    crop_mode: str,
    min_width: int,
    min_height: int,
) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    if canvas_w <= 0 or canvas_h <= 0:
        raise RuntimeError("No monitors detected")

    src = Image.open(image_path).convert("RGB")
    src_w, src_h = src.size
    if src_w < min_width or src_h < min_height:
        raise RuntimeError(f"NASA image too small for wallpaper use ({src_w}x{src_h}); minimum {min_width}x{min_height}")

    if crop_mode == "contain":
        scaled_w, scaled_h = fit_contain(src_w, src_h, canvas_w, canvas_h)
        resized = src.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (canvas_w, canvas_h), color=(0, 0, 0))
        x = (canvas_w - scaled_w) // 2
        y = (canvas_h - scaled_h) // 2
        canvas.paste(resized, (x, y))
        return canvas

    scaled_w, scaled_h = fit_cover(src_w, src_h, canvas_w, canvas_h)
    resized = src.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)

    x = (scaled_w - canvas_w) // 2
    if crop_mode == "smart_center":
        y = max(0, min(scaled_h - canvas_h, int((scaled_h - canvas_h) * 0.38)))
    else:
        y = (scaled_h - canvas_h) // 2

    return resized.crop((x, y, x + canvas_w, y + canvas_h))


def generate_wallpapers(
    image_path: pathlib.Path,
    monitors: List[Monitor],
    cache_dir: pathlib.Path,
    crop_mode: str,
    monitor_mode: str,
    min_width: int,
    min_height: int,
) -> Dict[str, pathlib.Path]:
    if not monitors:
        raise RuntimeError("No monitors detected")

    min_x, min_y, canvas_w, canvas_h = compute_virtual_canvas(monitors)

    if len(monitors) == 2:
        a, b = sorted(monitors, key=lambda m: m.x)
        if not (a.x + a.width == b.x and a.width == b.width == 1920 and a.height == b.height == 1080):
            logging.info("Non-phase-1 geometry detected; using generic spanning algorithm")

    if monitor_mode != "span":
        logging.info("Per-monitor mode is not implemented yet; falling back to span")

    virtual = render_virtual_canvas(image_path, (canvas_w, canvas_h), crop_mode, min_width, min_height)
    generated_dir = cache_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)

    span_path = generated_dir / "span.jpg"
    virtual.save(span_path, quality=94)

    outputs: Dict[str, pathlib.Path] = {}
    for mon in monitors:
        left = mon.x - min_x
        top = mon.y - min_y
        tile = virtual.crop((left, top, left + mon.width, top + mon.height))
        out = generated_dir / f"monitor_{mon.name}.jpg"
        tile.save(out, quality=94)
        outputs[mon.name] = out

    save_json(
        cache_dir / "state" / "layout.json",
        {
            "generated_at": int(time.time()),
            "canvas": {"x": min_x, "y": min_y, "width": canvas_w, "height": canvas_h},
            "monitors": [m.__dict__ for m in monitors],
            "outputs": {k: str(v) for k, v in outputs.items()},
            "span": str(span_path),
        },
    )

    return outputs


def apply_wallpaper(outputs: Dict[str, pathlib.Path]) -> None:
    if not outputs:
        raise RuntimeError("No generated images to apply")

    preferred = sorted(outputs.keys())[0]
    image = str(outputs[preferred])

    cmd = ["plasma-apply-wallpaperimage", image]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Failed to apply via plasma-apply-wallpaperimage. "
            "Keep this wallpaper plugin selected and it will still render images from cache. "
            f"stderr: {proc.stderr.strip()}"
        )


def pick_screen_specific_output(cache_dir: pathlib.Path, x: int, y: int, w: int, h: int) -> Optional[pathlib.Path]:
    layout = load_json(cache_dir / "state" / "layout.json", default={})
    for mon in layout.get("monitors", []):
        if mon.get("x") == x and mon.get("y") == y and mon.get("width") == w and mon.get("height") == h:
            out = layout.get("outputs", {}).get(mon.get("name"))
            if out and pathlib.Path(out).exists():
                return pathlib.Path(out)
    span = layout.get("span")
    if span and pathlib.Path(span).exists():
        return pathlib.Path(span)
    return None


def refresh(args: argparse.Namespace) -> pathlib.Path:
    cache_dir = resolve_cache_dir(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    image_path, metadata = fetch_nasa_image(
        provider=args.provider,
        api_key=args.api_key,
        cache_dir=cache_dir,
        min_width=args.min_width,
        min_height=args.min_height,
        lookback_days=args.apod_lookback_days,
        library_query=args.library_query,
        force=args.force,
    )
    save_json(cache_dir / "state" / "last_metadata.json", metadata)

    monitors = parse_xrandr()
    if not monitors and args.screen_width and args.screen_height:
        monitors = [Monitor(name="QMLScreen", x=args.screen_x, y=args.screen_y, width=args.screen_width, height=args.screen_height)]

    outputs = generate_wallpapers(
        image_path=image_path,
        monitors=monitors,
        cache_dir=cache_dir,
        crop_mode=args.crop_mode,
        monitor_mode=args.monitor_mode,
        min_width=args.min_width,
        min_height=args.min_height,
    )

    if args.apply:
        apply_wallpaper(outputs)

    chosen = pick_screen_specific_output(cache_dir, args.screen_x, args.screen_y, args.screen_width, args.screen_height)
    if chosen:
        return chosen

    return next(iter(outputs.values()))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["refresh"], help="operation to run")
    p.add_argument("--provider", choices=["library", "apod", "epic"], default="library")
    p.add_argument("--api-key", default="DEMO_KEY")
    p.add_argument("--cache-dir", default="")
    p.add_argument("--library-query", default="jwst nebula galaxy hubble", help="Query for NASA Image Library provider")
    p.add_argument("--crop-mode", choices=["cover", "contain", "smart_center"], default="cover")
    p.add_argument("--monitor-mode", choices=["span", "per_monitor"], default="span")
    p.add_argument("--min-width", type=int, default=3840)
    p.add_argument("--min-height", type=int, default=2160)
    p.add_argument("--apod-lookback-days", type=int, default=30)
    p.add_argument("--screen-x", type=int, default=0)
    p.add_argument("--screen-y", type=int, default=0)
    p.add_argument("--screen-width", type=int, default=0)
    p.add_argument("--screen-height", type=int, default=0)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--apply", action="store_true", help="Attempt to apply generated wallpaper via plasma-apply-wallpaperimage")
    return p


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Keep Pillow internals from flooding debug output.
    logging.getLogger("PIL").setLevel(logging.INFO)

    try:
        out = refresh(args)
    except Exception as exc:
        logging.error("refresh failed: %s", exc)
        return 1

    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
