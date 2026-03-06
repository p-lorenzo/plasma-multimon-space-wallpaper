# Architecture note

## End-to-end flow

1. `contents/ui/main.qml` (Plasma wallpaper frontend) triggers refresh on startup and by timer.
2. The QML layer calls `scripts/multimon_wallpaper.py refresh`.
3. The Python helper:
   - Fetches NASA images (APOD or EPIC) with cache reuse and minimum-size filtering.
   - Detects monitors from `xrandr`.
   - Builds one virtual desktop canvas.
   - Resizes/crops source image to the canvas.
   - Slices one image per monitor.
   - Stores generated images and state under cache.
4. QML receives the generated image path and renders it for the current wallpaper instance.

## Separation of concerns

- **Fetching**: `fetch_nasa_image`
- **Monitor detection**: `parse_xrandr`
- **Image processing/splitting**: `render_virtual_canvas`, `generate_wallpapers`
- **Plasma integration**: `contents/ui/main.qml`

## Plasma integration note

Plasma wallpaper plugins run once per screen containment. This prototype uses shared cache + per-screen geometry matching so each wallpaper instance can show the correct split tile.

`plasma-apply-wallpaperimage` support is included as an optional fallback from the helper (`--apply`), but the primary integration is to keep this plugin selected as the desktop wallpaper so it updates itself directly.

## Phase 1 scope

- Verified logic for 2 horizontal 1920x1080 monitors.
- Generic spanning algorithm is already present for non-phase-1 layouts, but not yet tuned.

## TODO (Phase 2+)

- Arbitrary monitor geometries and gaps with stronger validation.
- Mixed DPI / fractional scaling aware monitor coordinates.
- Subject-aware crop using saliency/face/semantic heuristics.
- Additional providers (NASA EPIC, ESA, Unsplash, custom feeds).


## Provider strategy

- APOD: scans backward across recent days (configurable lookback) until an image matches minimum width/height.
- EPIC: uses NASA EPIC natural-color image list as an alternative when APOD entries are too small or non-image.
