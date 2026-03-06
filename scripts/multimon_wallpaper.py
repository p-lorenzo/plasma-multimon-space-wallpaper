#!/usr/bin/env python3
"""Fetch NASA images and generate per-monitor wallpapers for Plasma 6."""

from __future__ import annotations

import argparse
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


def fetch_nasa_image(nasa_endpoint: str, api_key: str, cache_dir: pathlib.Path, force: bool = False) -> Tuple[pathlib.Path, dict]:
    state_path = cache_dir / "state" / "last_fetch.json"
    state = load_json(state_path, default={})

    query = urllib.parse.urlencode({"api_key": api_key})
    url = f"{nasa_endpoint}?{query}"
    logging.debug("Fetching NASA metadata: %s", url)

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"NASA API unavailable: {exc}") from exc

    image_url = metadata.get("hdurl") or metadata.get("url")
    if not image_url:
        raise RuntimeError("NASA response did not include an image URL")

    ext = pathlib.Path(urllib.parse.urlparse(image_url).path).suffix.lower() or ".jpg"
    image_id = metadata.get("date") or metadata.get("title") or str(int(time.time()))
    image_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", image_id)

    images_dir = cache_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    image_path = images_dir / f"{image_id}{ext}"

    if not force and state.get("image_url") == image_url and pathlib.Path(state.get("image_path", "")).exists():
        logging.info("Reusing cached NASA image: %s", state["image_path"])
        return pathlib.Path(state["image_path"]), metadata

    if not image_path.exists() or force:
        try:
            with urllib.request.urlopen(image_url, timeout=60) as response:
                image_path.write_bytes(response.read())
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Failed to download NASA image: {exc}") from exc

    save_json(
        state_path,
        {
            "image_url": image_url,
            "image_path": str(image_path),
            "fetched_at": int(time.time()),
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


def render_virtual_canvas(image_path: pathlib.Path, canvas_size: Tuple[int, int], crop_mode: str) -> Image.Image:
    canvas_w, canvas_h = canvas_size
    if canvas_w <= 0 or canvas_h <= 0:
        raise RuntimeError("No monitors detected")

    src = Image.open(image_path).convert("RGB")
    src_w, src_h = src.size
    if src_w < 1000 or src_h < 1000:
        raise RuntimeError("NASA image too small for wallpaper use")

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

    virtual = render_virtual_canvas(image_path, (canvas_w, canvas_h), crop_mode)
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
        nasa_endpoint=args.nasa_endpoint,
        api_key=args.api_key,
        cache_dir=cache_dir,
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
    p.add_argument("--nasa-endpoint", default="https://api.nasa.gov/planetary/apod")
    p.add_argument("--api-key", default="DEMO_KEY")
    p.add_argument("--cache-dir", default="")
    p.add_argument("--crop-mode", choices=["cover", "contain", "smart_center"], default="cover")
    p.add_argument("--monitor-mode", choices=["span", "per_monitor"], default="span")
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

    try:
        out = refresh(args)
    except Exception as exc:
        logging.error("refresh failed: %s", exc)
        return 1

    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
