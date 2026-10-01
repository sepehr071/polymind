"""Regenerate dashboard hub icons with a locked design language.

Uses OpenRouter Image API. A single style-master plate is generated first;
every tool icon is image-edited from that master so frame / lighting /
materials stay identical — only the center metaphor changes.

Usage (from repo root, backend venv):
  python backend/scripts/gen_hub_icons.py              # skip existing
  python backend/scripts/gen_hub_icons.py --force      # rebuild all
  python backend/scripts/gen_hub_icons.py agent chat   # subset

Retired for the ERP colored tiles (2026-09-28). The committed PNGs in
frontend/src/assets/hub-icons/ are the source. Do not --force this script;
its style bible still paints the old blue glass.
"""
from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

OUT = ROOT / "frontend" / "src" / "assets" / "hub-icons"
MASTER = OUT / "_style_master.png"
KEY = os.environ.get("OPENROUTER_API_KEY")
if not KEY:
    sys.exit("OPENROUTER_API_KEY missing")

MODEL = os.environ.get("HUB_ICON_MODEL", "google/gemini-3.1-flash-image")
BASE = "https://openrouter.ai/api/v1/images"
SIZE_PX = 192

# Locked design language — every icon must obey this exactly.
STYLE_BIBLE = """
DESIGN SYSTEM (must match style reference image EXACTLY):
- Single iOS-style squircle app icon, front-facing, centered in frame
- Soft 3D clay / frosted-glass material, subtle thickness
- ALWAYS the same background: smooth royal-blue → soft periwinkle vertical gradient
  (about #1E47D1 top-left to #7B8CFF bottom-right). Never white, never multi-hue rainbow,
  never photo, never landscape, never flat solid unrelated color.
- ALWAYS the same lighting: soft top-left specular glass highlight + gentle bottom shadow
- ALWAYS the same corner radius and outer soft glow on a matching blue field
- Center glyph only: simple single object, soft white / pale ice-blue glass with light
  rim light. No text, no letters, no numbers, no watermark, no logo wordmarks.
- Keep glyph scale ~45–55% of the tile; same camera angle as the reference
- Output must look like one coherent icon pack, not mixed styles
""".strip()

MASTER_PROMPT = f"""{STYLE_BIBLE}

Subject for this plate: a simple multi-point spark / star as the center glyph
(soft white-ice glass). This is the STYLE MASTER for an AI SaaS icon set.
"""

# Center-glyph only — style comes from the master reference.
ICONS: dict[str, str] = {
    "agent": "glowing multi-point spark with a small neural sphere core",
    "chat": "two overlapping speech bubbles",
    "arena": "2x2 grid of four equal rounded panels",
    "debate": "elegant balance scales",
    "imageStudio": "magic paintbrush with a soft light stroke",
    "dataAnalyzer": "three rising bar-chart columns",
    "payroll": "document sheet with a small currency symbol and checkmark",
    "presentations": "tilted stack of two presentation slides",
    "ocr": "document page with a horizontal scan line",
    "emailWriter": "open envelope with a small letter inside",
    "cvChecker": "resume card with a person silhouette and check",
    "research": "telescope over a small book",
    "contracts": "formal document with a shield seal",
    "tenders": "clipboard with checklist marks",
    "shop": "shopping cart",
    "workflow": "three connected nodes with curved links",
    "automateAgent": "friendly small robot head",
    "meetings": "studio microphone with soft sound arcs",
    "aiPersonas": "friendly user bust silhouette with a spark",
    "knowledgeVault": "open book with a small crystal of light",
}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://unichat.example.com",
        "X-Title": "Polymind hub icons",
    }


def _decode_image_payload(item: dict) -> bytes:
    b64 = item.get("b64_json") or item.get("b64")
    url = item.get("url")
    if b64:
        if isinstance(b64, str) and b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
    if url:
        with httpx.Client(timeout=60.0) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.content
    raise RuntimeError(f"no b64/url in {list(item.keys())}")


def _post_image(payload: dict) -> bytes:
    with httpx.Client(timeout=180.0) as client:
        r = client.post(BASE, headers=_headers(), json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        items = data.get("data") or data.get("images") or []
        if not items:
            raise RuntimeError(f"empty response keys={list(data.keys())}")
        return _decode_image_payload(items[0])


def generate_master() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    raw = _post_image(
        {
            "model": MODEL,
            "prompt": MASTER_PROMPT,
            "n": 1,
            "size": "1024x1024",
            "aspect_ratio": "1:1",
        }
    )
    MASTER.write_bytes(raw)
    return MASTER


def generate_from_master(slug: str, subject: str, master_data_uri: str) -> bytes:
    prompt = f"""{STYLE_BIBLE}

Use the attached image as the ABSOLUTE style reference.
Copy its frame, gradient, glass material, lighting, and proportions EXACTLY.
ONLY replace the center glyph with: {subject}.
Do not change background color family. Do not add extra objects or text.
"""
    return _post_image(
        {
            "model": MODEL,
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
            "aspect_ratio": "1:1",
            "input_references": [
                {"type": "image_url", "image_url": {"url": master_data_uri}},
            ],
        }
    )


def save_icon(slug: str, raw: bytes) -> Path:
    dest = OUT / f"{slug}.png"
    tmp = OUT / f"._{slug}.raw.png"
    tmp.write_bytes(raw)
    im = Image.open(tmp).convert("RGBA")
    im = im.resize((SIZE_PX, SIZE_PX), Image.Resampling.LANCZOS)
    im.save(dest, format="PNG", optimize=True)
    tmp.unlink(missing_ok=True)
    return dest


def main() -> None:
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]

    print("== style master")
    if force or not MASTER.exists() or MASTER.stat().st_size < 10_000:
        generate_master()
        print(f"master -> {MASTER.name} ({MASTER.stat().st_size} bytes)")
    else:
        print(f"reuse {MASTER.name}")

    master_b64 = base64.b64encode(MASTER.read_bytes()).decode("ascii")
    master_uri = f"data:image/png;base64,{master_b64}"

    items = [(k, v) for k, v in ICONS.items() if not only or k in only]
    ok = fail = 0
    for slug, subject in items:
        dest = OUT / f"{slug}.png"
        if dest.exists() and dest.stat().st_size > 5_000 and not force and not only:
            print(f"skip {slug}")
            ok += 1
            continue
        try:
            raw = generate_from_master(slug, subject, master_uri)
            p = save_icon(slug, raw)
            print(f"ok {slug} -> {p.name} ({p.stat().st_size} bytes)")
            ok += 1
            time.sleep(0.35)
        except Exception as e:
            print(f"FAIL {slug}: {e}")
            fail += 1
    print(f"done ok={ok} fail={fail}")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
