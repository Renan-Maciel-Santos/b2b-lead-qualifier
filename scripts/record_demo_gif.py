"""Script to record an automated demonstration GIF of the B2B Lead Qualifier dashboard.

Captures a reproducible sequence of frames using local headless Chrome via CDP
at 1280x720 resolution, with subtitles in Portuguese, and compiles an optimized
looping GIF with a single unified color palette and zero background dithering.
"""

import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

import websockets
from PIL import Image

DEMO_KEY = os.environ.get("DEMO_API_KEY", "b2b_live_demo_acme_111111111111111111111111")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
OUTPUT_PATH = Path("docs/images/demo.gif")
VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 720
TEST_BACKGROUND_COORDINATE = (20, 200)


def find_chrome_binary() -> str:
    """Locate the Chrome executable on Windows, Linux, or macOS."""
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]

    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand

    which_chrome = shutil.which("chrome") or shutil.which("google-chrome")
    if which_chrome:
        return which_chrome

    raise FileNotFoundError(
        "Google Chrome executable not found. Set CHROME_PATH environment variable."
    )


async def cdp_call(
    ws: Any,
    method: str,
    params: dict[str, Any] | None = None,
    msg_id: list[int] | None = None,
) -> dict[str, Any]:
    """Execute a Chrome DevTools Protocol command over WebSocket."""
    if msg_id is None:
        msg_id = [1]
    current_id = msg_id[0]
    msg_id[0] += 1
    req = {"id": current_id, "method": method, "params": params or {}}
    await ws.send(json.dumps(req))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == current_id:
            raw_result = resp.get("result", {})
            if isinstance(raw_result, dict):
                return raw_result
            return {}


async def capture_frame(ws: Any, msg_id: list[int]) -> Image.Image:
    """Capture the current viewport as a PIL Image in RGB mode."""
    shot_res = await cdp_call(ws, "Page.captureScreenshot", {"format": "png"}, msg_id)
    img_bytes = base64.b64decode(shot_res["data"])
    temp_img = Image.open(io.BytesIO(img_bytes))
    return temp_img.convert("RGB")


async def execute_js(ws: Any, expression: str, msg_id: list[int]) -> Any:
    """Evaluate a JavaScript expression in the browser context."""
    res = await cdp_call(
        ws,
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True},
        msg_id,
    )
    return res.get("result", {}).get("value")


async def record_frames() -> tuple[list[Image.Image], list[int]]:
    """Record frames and durations across the 4 storyboard stages."""
    chrome_bin = find_chrome_binary()
    temp_dir = tempfile.mkdtemp(prefix="chrome_gif_")

    proc = subprocess.Popen(
        [
            chrome_bin,
            "--headless=new",
            "--remote-debugging-port=9222",
            f"--user-data-dir={temp_dir}",
            f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT}",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    frames: list[Image.Image] = []
    durations: list[int] = []

    try:
        # Give Chrome a moment to initialize the CDP endpoint
        await asyncio.sleep(2.0)

        # Open dashboard tab
        new_tab_url = f"http://127.0.0.1:9222/json/new?{BASE_URL}/dashboard"
        req = urllib.request.Request(new_tab_url, method="PUT")
        with urllib.request.urlopen(req) as resp:
            tab_data = json.loads(resp.read().decode())

        ws_url = tab_data["webSocketDebuggerUrl"]

        async with websockets.connect(ws_url) as ws:
            msg_id = [1]
            await cdp_call(ws, "Page.enable", {}, msg_id)
            await cdp_call(ws, "Runtime.enable", {}, msg_id)

            await cdp_call(
                ws,
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": VIEWPORT_WIDTH,
                    "height": VIEWPORT_HEIGHT,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                },
                msg_id,
            )

            await asyncio.sleep(1.0)

            # Inject the discrete footer caption banner with >= 20px font size and proportional height
            init_caption_js = """
            (() => {
                let banner = document.getElementById('demoCaptionBanner');
                if (!banner) {
                    banner = document.createElement('div');
                    banner.id = 'demoCaptionBanner';
                    banner.style.position = 'fixed';
                    banner.style.bottom = '0';
                    banner.style.left = '0';
                    banner.style.right = '0';
                    banner.style.height = '64px';
                    banner.style.backgroundColor = '#ffffff';
                    banner.style.borderTop = '1px solid #d2d7df';
                    banner.style.display = 'flex';
                    banner.style.alignItems = 'center';
                    banner.style.justifyContent = 'center';
                    banner.style.fontFamily = "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
                    banner.style.fontSize = '21px';
                    banner.style.fontWeight = '600';
                    banner.style.color = '#1f4e78';
                    banner.style.letterSpacing = '0.01em';
                    banner.style.boxShadow = '0 -2px 10px rgba(0, 0, 0, 0.05)';
                    banner.style.zIndex = '999999';
                    document.body.appendChild(banner);
                    document.body.style.paddingBottom = '72px';
                }
                banner.textContent = '1. O operador informa uma key com escopo leads:read';
            })()
            """
            await execute_js(ws, init_caption_js, msg_id)
            await asyncio.sleep(0.5)

            # Stage A: Initial state without key (2.4s)
            # Legenda: "1. O operador informa uma key com escopo leads:read"
            print("[Stage A] Initial state without key...")
            # Frame 1: Empty field, auth notice visible
            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            # Frame 2: Focus on password input
            await execute_js(ws, "document.getElementById('apiKeyInput').focus();", msg_id)
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            # Frame 3: Ready to type
            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            # Stage B: Typing key (masked password) and clicking button (~2.2s)
            # Legenda: "2. Consulta autenticada à API"
            print("[Stage B] Typing password and clicking button...")
            await execute_js(
                ws,
                "document.getElementById('demoCaptionBanner').textContent = '2. Consulta autenticada à API';",
                msg_id,
            )

            # Frame 1: Partial password bullets
            await execute_js(
                ws,
                "document.getElementById('apiKeyInput').value = 'b2b_live_demo';",
                msg_id,
            )
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(600)

            # Frame 2: Full key in password input (bullets masked by browser)
            await execute_js(
                ws,
                f"document.getElementById('apiKeyInput').value = '{DEMO_KEY}';",
                msg_id,
            )
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            # Frame 3: Click effect on button while subtitle 2 is displayed
            click_btn_js = """
            (() => {
                const btn = document.getElementById('connectBtn');
                btn.style.transform = 'scale(0.97)';
                btn.style.backgroundColor = '#084273';
            })()
            """
            await execute_js(ws, click_btn_js, msg_id)
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            # Trigger API fetch and restore button style
            trigger_fetch_js = f"""
            (() => {{
                const btn = document.getElementById('connectBtn');
                btn.style.transform = '';
                btn.style.backgroundColor = '';
                fetchLeads('{DEMO_KEY}');
            }})()
            """
            await execute_js(ws, trigger_fetch_js, msg_id)

            # Wait for data to load in DOM before capturing stage C
            for _ in range(30):
                await asyncio.sleep(0.2)
                row_count = await execute_js(
                    ws,
                    "document.querySelectorAll('#leadsTableBody tr').length",
                    msg_id,
                )
                if (row_count or 0) >= 3:
                    break

            # Stage C: Loaded leads with rule breakdown (~2.7s)
            # Legenda: "3. Cada nota mostra a composição por regra e a distância até o corte"
            # Crucial: Change caption to Stage 3 BEFORE capturing the first frame with the table visible!
            print("[Stage C] Loaded leads with rule breakdown...")
            await execute_js(
                ws,
                "document.getElementById('demoCaptionBanner').textContent = '3. Cada nota mostra a composição por regra e a distância até o corte';",
                msg_id,
            )
            await asyncio.sleep(0.3)

            for _ in range(3):
                frames.append(await capture_frame(ws, msg_id))
                durations.append(900)

            # Stage D: Highlight disqualified / knockout lead (~2.7s)
            # Legenda: "4. Regras eliminatórias encerram a avaliação na hora"
            # Uses dashboard palette: background --color-disq-bg (#fbe8e8), outline --color-disq (#8d1d1d)
            print("[Stage D] Highlight disqualified / knockout lead with dashboard palette...")
            highlight_js = """
            (() => {
                document.getElementById('demoCaptionBanner').textContent = '4. Regras eliminatórias encerram a avaliação na hora';
                const rows = document.querySelectorAll('#leadsTableBody tr');
                rows.forEach(r => {
                    if (r.textContent.includes('Eliminado') || r.textContent.includes('estudante')) {
                        r.style.backgroundColor = 'var(--color-disq-bg, #fbe8e8)';
                        r.style.outline = '2px solid var(--color-disq, #8d1d1d)';
                        r.style.outlineOffset = '-2px';
                        r.style.transition = 'none';
                    } else {
                        r.style.opacity = '0.55';
                        r.style.transition = 'none';
                    }
                });
            })()
            """
            await execute_js(ws, highlight_js, msg_id)
            await asyncio.sleep(0.3)

            for _ in range(3):
                frames.append(await capture_frame(ws, msg_id))
                durations.append(900)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return frames, durations


def build_unified_palette(frames: list[Image.Image]) -> Image.Image:
    """Create a single global palette covering all storyboard stages."""
    # Combine frames from Stage A, Stage C (loaded table) and Stage D (disqualified highlight)
    # into a single reference canvas to derive an optimal 256-color palette
    sample_indices = [0, len(frames) // 2, len(frames) - 1]
    ref_w = VIEWPORT_WIDTH
    ref_h = VIEWPORT_HEIGHT * len(sample_indices)
    palette_canvas = Image.new("RGB", (ref_w, ref_h))

    for idx, frame_idx in enumerate(sample_indices):
        palette_canvas.paste(frames[frame_idx], (0, idx * VIEWPORT_HEIGHT))

    # Generate 256-color palette using adaptive quantization
    palette_base = palette_canvas.quantize(colors=256, method=Image.Resampling.LANCZOS)
    return palette_base


def build_optimized_gif(frames: list[Image.Image], durations: list[int], output_path: Path) -> int:
    """Compile frames into a single-palette looping GIF without background dithering."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Deriving unified color palette from {len(frames)} storyboard frames...")
    palette_base = build_unified_palette(frames)

    # Quantize every frame strictly using the exact same master palette and NO dithering
    # This prevents subtle palette index shifts and color fluctuation across frames
    quantized_frames = []
    for frame in frames:
        q_frame = frame.quantize(palette=palette_base, dither=Image.Dither.NONE)
        quantized_frames.append(q_frame)

    quantized_frames[0].save(
        output_path,
        save_all=True,
        append_images=quantized_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )

    size_bytes = output_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    print(f"GIF saved successfully: {output_path} ({size_bytes} bytes / {size_mb:.2f} MB)")
    return size_bytes


def verify_background_consistency(
    gif_path: Path, coord: tuple[int, int] = TEST_BACKGROUND_COORDINATE
) -> tuple[int, int, int]:
    """Programmatically verify that background pixel color is identical across all GIF frames."""
    with Image.open(gif_path) as im:
        expected_color: tuple[int, int, int] | None = None
        frame_count: int = getattr(im, "n_frames", 1)
        for i in range(frame_count):
            im.seek(i)
            rgb_frame = im.convert("RGB")
            color = rgb_frame.getpixel(coord)
            if not isinstance(color, tuple) or len(color) < 3:
                raise TypeError(f"Unexpected pixel format at frame {i}: {color}")
            rgb_color: tuple[int, int, int] = (color[0], color[1], color[2])
            if expected_color is None:
                expected_color = rgb_color
            elif rgb_color != expected_color:
                raise ValueError(
                    f"Background color fluctuation at frame {i}: got {rgb_color}, expected {expected_color} at {coord}"
                )

        if expected_color is None:
            raise RuntimeError("GIF contains zero frames for background color verification.")

        print(
            f"Verification PASSED: all {frame_count} frames have identical background color {expected_color} at coordinate {coord}"
        )
        return expected_color


def main() -> None:
    """Main execution function."""
    print("================================================================================")
    print(" Recording B2B Lead Qualifier Demo GIF (1280x720 - Unified Palette)")
    print("================================================================================")
    frames, durations = asyncio.run(record_frames())
    size_bytes = build_optimized_gif(frames, durations, OUTPUT_PATH)

    if size_bytes > 5 * 1024 * 1024:
        raise ValueError(f"GIF size ({size_bytes} bytes) exceeds 5 MB limit!")

    bg_color = verify_background_consistency(OUTPUT_PATH)

    with Image.open(OUTPUT_PATH) as im:
        actual_frames: int = getattr(im, "n_frames", 1)

    print(
        f"Final GIF metrics: {size_bytes} bytes, {actual_frames} frames in file, background color={bg_color}"
    )


if __name__ == "__main__":
    main()
