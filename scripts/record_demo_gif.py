"""Script to record an automated demonstration GIF of the B2B Lead Qualifier dashboard.

Captures a reproducible sequence of frames using local headless Chrome via CDP
at 1280x720 resolution, with subtitles in Portuguese, and compiles an optimized
looping GIF using Pillow.
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
    """Capture the current viewport as a PIL Image."""
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

            # Inject the discrete footer caption banner
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
                    banner.style.height = '46px';
                    banner.style.backgroundColor = '#ffffff';
                    banner.style.borderTop = '1px solid #d5dbe1';
                    banner.style.display = 'flex';
                    banner.style.alignItems = 'center';
                    banner.style.justifyContent = 'center';
                    banner.style.fontFamily = "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
                    banner.style.fontSize = '14px';
                    banner.style.fontWeight = '500';
                    banner.style.color = '#1f4e78';
                    banner.style.letterSpacing = '0.01em';
                    banner.style.boxShadow = '0 -2px 8px rgba(0, 0, 0, 0.04)';
                    banner.style.zIndex = '999999';
                    document.body.appendChild(banner);
                    document.body.style.paddingBottom = '54px';
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

            # Stage B: Typing key (masked password) and clicking button (2.5s)
            # Legenda: "2. Consulta autenticada à API"
            print("[Stage B] Typing password and clicking connect...")
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

            # Frame 2: Full key in password input (bullet masked by browser)
            await execute_js(
                ws,
                f"document.getElementById('apiKeyInput').value = '{DEMO_KEY}';",
                msg_id,
            )
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(700)

            # Frame 3: Click effect on button
            click_btn_js = """
            (() => {
                const btn = document.getElementById('connectBtn');
                btn.style.transform = 'scale(0.97)';
                btn.style.backgroundColor = '#163b5c';
            })()
            """
            await execute_js(ws, click_btn_js, msg_id)
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(600)

            # Trigger actual fetch
            trigger_fetch_js = f"""
            (() => {{
                const btn = document.getElementById('connectBtn');
                btn.style.transform = '';
                btn.style.backgroundColor = '';
                fetchLeads('{DEMO_KEY}');
            }})()
            """
            await execute_js(ws, trigger_fetch_js, msg_id)

            # Wait for data to load
            for _ in range(25):
                await asyncio.sleep(0.2)
                row_count = await execute_js(
                    ws,
                    "document.querySelectorAll('#leadsTableBody tr').length",
                    msg_id,
                )
                if (row_count or 0) >= 3:
                    break

            await asyncio.sleep(0.4)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(600)

            # Stage C: Loaded leads with rule breakdown (2.8s)
            # Legenda: "3. Cada nota mostra a composição por regra e a distância até o corte"
            print("[Stage C] Loaded leads with rule breakdown...")
            await execute_js(
                ws,
                "document.getElementById('demoCaptionBanner').textContent = '3. Cada nota mostra a composição por regra e a distância até o corte';",
                msg_id,
            )
            await asyncio.sleep(0.3)

            for _ in range(4):
                frames.append(await capture_frame(ws, msg_id))
                durations.append(700)

            # Stage D: Highlight disqualified / knockout lead (2.8s)
            # Legenda: "4. Regras eliminatórias encerram a avaliação na hora"
            print("[Stage D] Highlight disqualified / knockout lead...")
            highlight_js = """
            (() => {
                document.getElementById('demoCaptionBanner').textContent = '4. Regras eliminatórias encerram a avaliação na hora';
                const rows = document.querySelectorAll('#leadsTableBody tr');
                rows.forEach(r => {
                    if (r.textContent.includes('Eliminado') || r.textContent.includes('estudante')) {
                        r.style.backgroundColor = '#fff7ed';
                        r.style.outline = '2px solid #ea580c';
                        r.style.outlineOffset = '-2px';
                        r.style.transition = 'all 0.3s ease';
                    } else {
                        r.style.opacity = '0.55';
                        r.style.transition = 'all 0.3s ease';
                    }
                });
            })()
            """
            await execute_js(ws, highlight_js, msg_id)
            await asyncio.sleep(0.3)

            for _ in range(4):
                frames.append(await capture_frame(ws, msg_id))
                durations.append(700)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return frames, durations


def build_optimized_gif(frames: list[Image.Image], durations: list[int], output_path: Path) -> int:
    """Compile frames into an optimized looping GIF under 5 MB."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Compiling GIF with {len(frames)} frames...")

    # Quantize frames to reduce color palette and file size
    # Using adaptive palette (128 colors is crisp for web ledger UI)
    quantized_frames = []
    for frame in frames:
        # Convert to P mode with adaptive palette
        q_frame = frame.quantize(colors=128, method=Image.Resampling.LANCZOS)
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


def main() -> None:
    """Main execution function."""
    print("================================================================================")
    print(" Recording B2B Lead Qualifier Demo GIF (1280x720)")
    print("================================================================================")
    frames, durations = asyncio.run(record_frames())
    size_bytes = build_optimized_gif(frames, durations, OUTPUT_PATH)

    if size_bytes > 5 * 1024 * 1024:
        raise ValueError(f"GIF size ({size_bytes} bytes) exceeds 5 MB limit!")


if __name__ == "__main__":
    main()
