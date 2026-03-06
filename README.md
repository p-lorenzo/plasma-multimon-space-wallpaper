# plasma-multimon-space-wallpaper

KDE Plasma 6 wallpaper plugin that fetches high-resolution NASA imagery, builds a virtual multi-monitor canvas, slices it per display, and renders generated wallpapers from local cache.

License: MIT.

## Plasma 6 package conventions used

This project is scaffolded as a **Plasma 6 wallpaper package** (not a generic plasmoid):

- `metadata.json` with `KPackageStructure: Plasma/Wallpaper`
- `X-Plasma-API: declarativeappletscript`
- `X-Plasma-MainScript: ui/main.qml`
- `contents/ui/main.qml` as the wallpaper entrypoint
- `contents/config/` for wallpaper configuration schema + UI

> Note: Plasma API details vary slightly across distro versions. This repo uses the safest current structure for QML wallpaper packages in Plasma 6 and provides a helper fallback path.

## Features (prototype)

- NASA image providers: NASA Image Library (recommended), APOD (`hdurl` preferred), and EPIC.
- Local metadata/state caching.
- Download de-duplication (unless `--force`).
- Minimum source image size filter (default 3840x2160).
- APOD lookback scan to skip small/non-image entries.
- Monitor layout detection via `xrandr`.
- Virtual desktop canvas composition.
- Crop modes:
  - `cover`
  - `contain`
  - `smart_center`
- Slicing into one output image per monitor.
- Configurable refresh interval.
- Manual “Refresh now” wallpaper action.
- Debug logging option.
- Optional `plasma-apply-wallpaperimage` fallback in helper CLI.

## Phase 1 target

- First-class simple case: **2 side-by-side 1920x1080 monitors**.
- Generic spanning logic exists for other layouts but is marked as not fully tuned yet.

## Repository layout

```text
.
├── contents
│   ├── config
│   │   ├── config.qml
│   │   └── main.xml
│   └── ui
│       └── main.qml
├── docs
│   └── ARCHITECTURE.md
├── scripts
│   └── multimon_wallpaper.py
├── .gitignore
├── LICENSE
├── metadata.json
└── README.md
```

## Dependencies

Runtime:

- KDE Plasma 6
- Python 3.10+
- Pillow (`python-pillow`)
- `xrandr`

Optional fallback:

- `plasma-apply-wallpaperimage`

## Local development

From repo root:

```bash
python3 -m pip install --user pillow
python3 scripts/multimon_wallpaper.py refresh --debug
```

Expected output: printed absolute path to generated image.

Cache defaults to:

```text
~/.cache/plasma-multimon-space-wallpaper/
```

## Install as Plasma wallpaper plugin

### Option A: kpackagetool6

```bash
kpackagetool6 --type Plasma/Wallpaper --install .
```

Update:

```bash
kpackagetool6 --type Plasma/Wallpaper --upgrade .
```

Remove:

```bash
kpackagetool6 --type Plasma/Wallpaper --remove com.github.plasma.multimon.space.wallpaper
```

### Option B: manual local package path

```bash
mkdir -p ~/.local/share/plasma/wallpapers/com.github.plasma.multimon.space.wallpaper
rsync -a --delete ./ ~/.local/share/plasma/wallpapers/com.github.plasma.multimon.space.wallpaper/
```

Then select **Multi-monitor Space Wallpaper** in desktop wallpaper settings.


## Troubleshooting install

If you get errors like:

- `Package type "Wallpaper" not found`
- `Could not load package structure Wallpaper`

it means the package type was passed incorrectly. Use `Plasma/Wallpaper` (with the `Plasma/` prefix).

Also make sure you run `kpackagetool6` from the plugin root (the directory containing `metadata.json` and `contents/`).

## Configuration UI

Options provided:

- NASA provider (`library`, `apod`, or `epic`)
- NASA Image Library query
- NASA API key
- Refresh interval (hours)
- Cache directory
- Crop mode (`cover`, `contain`, `smart_center`)
- Monitor mode (`span`, `per_monitor` placeholder)
- Debug logging toggle


## Provider notes

### NASA Image Library (recommended)
- Uses `images-api.nasa.gov` search + asset endpoints and picks the first candidate above your minimum size.
- Better for dual-monitor needs because there are many high-resolution assets.

### APOD
- APOD metadata does **not** expose pixel dimensions, so this project now scans backwards up to `--apod-lookback-days` and only accepts images above your configured minimum size.
- If a day is a video/non-image entry, it is skipped automatically.

### EPIC
- EPIC gives Earth imagery from DSCOVR and is usually stable in resolution.
- Use `provider=epic` when APOD keeps returning assets that are too small for dual-monitor wallpapers.

## Testing commands

```bash
python3 scripts/multimon_wallpaper.py refresh --provider library --library-query "jwst nebula" --min-width 3840 --min-height 2160 --debug
python3 scripts/multimon_wallpaper.py refresh --provider apod --apod-lookback-days 60 --crop-mode contain --force
python3 scripts/multimon_wallpaper.py refresh --provider epic --min-width 3000 --min-height 2000 --crop-mode smart_center
```

## Packaging

Create distributable archive:

```bash
zip -r plasma-multimon-space-wallpaper.zip metadata.json contents scripts docs LICENSE README.md .gitignore
```

Install from archive:

```bash
kpackagetool6 --type Plasma/Wallpaper --install plasma-multimon-space-wallpaper.zip
```

## Error handling behavior

Graceful handling for:

- no network / NASA API unavailable
- no monitors detected
- NASA image too small
- invalid cached JSON
- command/runtime failures (non-zero with logs, no hard crash)

## Known limitations and next steps

- `per_monitor` mode is currently a placeholder that falls back to spanning.
- Mixed DPI/fractional scaling needs explicit geometry normalization.
- More providers beyond NASA are planned.
- Better semantic crop is planned.

See `docs/ARCHITECTURE.md` TODO section.
