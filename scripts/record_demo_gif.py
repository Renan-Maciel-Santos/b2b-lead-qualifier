"""Script to record an automated demonstration GIF of the B2B Lead Qualifier dashboard.

Captures a reproducible sequence of frames using local headless Chrome via CDP
at 1280x720 resolution, with subtitles in Portuguese, and compiles an optimized
looping GIF with a single unified color palette using Image.Quantize.MEDIANCUT,
zero dithering, and programmatic color fidelity verification.
"""

import asyncio
import base64
import io
import json
import os
import shutil
import subprocess
import sys
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
MAX_ALLOWED_COLOR_CHANNEL_DIFF = 3

# Exact design system anchor colors from dashboard CSS variables
EXACT_PALETTE_ANCHORS = [
    (241, 243, 246),  # --bg-canvas #f1f3f6
    (255, 255, 255),  # --bg-surface #ffffff
    (31, 78, 120),  # --seg-role #1f4e78
    (42, 117, 126),  # --seg-rev #2a757e
    (74, 101, 114),  # --seg-size #4a6572
    (251, 232, 232),  # --color-disq-bg #fbe8e8
    (141, 29, 29),  # --color-disq #8d1d1d
    (24, 32, 43),  # --text-main #18202b
    (11, 87, 150),  # --color-brand #0b5796
    (8, 66, 115),  # --color-brand-hover #084273
    (13, 94, 63),  # --color-qual #0d5e3f
    (228, 244, 236),  # --color-qual-bg #e4f4ec
    (141, 79, 0),  # --color-notqual #8d4f00
    (255, 244, 229),  # --color-notqual-bg #fff4e5
    (210, 215, 223),  # --border-subtle #d2d7df
    (83, 97, 115),  # --text-muted #536173
]


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


async def record_frames() -> tuple[list[Image.Image], list[int], dict[str, Image.Image]]:
    """Record frames, durations, and key raw reference frames across the 4 storyboard stages."""
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
    stage_raw_samples: dict[str, Image.Image] = {}

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

            # Inject discrete footer caption banner with >= 20px font and proportional height
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
            # Subtitle: "1. O operador informa uma key com escopo leads:read"
            print("[Stage A] Initial state without key...")
            raw_a = await capture_frame(ws, msg_id)
            frames.append(raw_a)
            durations.append(800)
            stage_raw_samples["Stage A"] = raw_a

            await execute_js(ws, "document.getElementById('apiKeyInput').focus();", msg_id)
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            frames.append(await capture_frame(ws, msg_id))
            durations.append(800)

            # Stage B: Typing key (masked password) and clicking button (~2.2s)
            # Subtitle: "2. Consulta autenticada à API"
            print("[Stage B] Typing password and clicking button...")
            await execute_js(
                ws,
                "document.getElementById('demoCaptionBanner').textContent = '2. Consulta autenticada à API';",
                msg_id,
            )

            await execute_js(
                ws,
                "document.getElementById('apiKeyInput').value = 'b2b_live_demo';",
                msg_id,
            )
            await asyncio.sleep(0.2)
            frames.append(await capture_frame(ws, msg_id))
            durations.append(600)

            await execute_js(
                ws,
                f"document.getElementById('apiKeyInput').value = '{DEMO_KEY}';",
                msg_id,
            )
            await asyncio.sleep(0.2)
            raw_b = await capture_frame(ws, msg_id)
            frames.append(raw_b)
            durations.append(800)
            stage_raw_samples["Stage B"] = raw_b

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

            # Wait for data to load in DOM before capturing Stage C
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
            # Subtitle: "3. Cada nota mostra a composição por regra e a distância até o corte"
            # Crucial requirement: Change subtitle to Stage 3 BEFORE capturing the first frame with the table visible!
            print("[Stage C] Loaded leads with rule breakdown...")
            await execute_js(
                ws,
                "document.getElementById('demoCaptionBanner').textContent = '3. Cada nota mostra a composição por regra e a distância até o corte';",
                msg_id,
            )
            await asyncio.sleep(0.3)

            raw_c = await capture_frame(ws, msg_id)
            frames.append(raw_c)
            durations.append(900)
            stage_raw_samples["Stage C"] = raw_c

            for _ in range(2):
                frames.append(await capture_frame(ws, msg_id))
                durations.append(900)

            # Stage D: Highlight disqualified / knockout lead (~2.7s)
            # Subtitle: "4. Regras eliminatórias encerram a avaliação na hora"
            # Strict dashboard palette: background --color-disq-bg (#fbe8e8), outline --color-disq (#8d1d1d)
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

            raw_d = await capture_frame(ws, msg_id)
            frames.append(raw_d)
            durations.append(900)
            stage_raw_samples["Stage D"] = raw_d

            for _ in range(2):
                frames.append(await capture_frame(ws, msg_id))
                durations.append(900)

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        shutil.rmtree(temp_dir, ignore_errors=True)

    return frames, durations, stage_raw_samples


def build_unified_palette(frames: list[Image.Image]) -> Image.Image:
    """Create a single global palette covering all storyboard stages using Image.Quantize.MEDIANCUT."""
    sample_indices = [0, len(frames) // 2, len(frames) - 1]
    ref_w = VIEWPORT_WIDTH
    ref_h = VIEWPORT_HEIGHT * len(sample_indices)
    palette_canvas = Image.new("RGB", (ref_w, ref_h))

    for idx, frame_idx in enumerate(sample_indices):
        palette_canvas.paste(frames[frame_idx], (0, idx * VIEWPORT_HEIGHT))

    # 1. Base quantization with MEDIANCUT algorithm
    pal_base = palette_canvas.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    raw_palette = list(pal_base.getpalette() or [])

    palette_colors = [list(raw_palette[i * 3 : i * 3 + 3]) for i in range(256)]

    # 2. Sanitize near-whites into pure white (255, 255, 255)
    for c in palette_colors:
        if c[0] >= 249 and c[1] >= 249 and c[2] >= 249:
            c[0], c[1], c[2] = 255, 255, 255

    # 3. Snap entries in vicinity of background canvas (241, 243, 246)
    for c in palette_colors:
        dist_bg = sum((c[i] - (241 if i == 0 else 243 if i == 1 else 246)) ** 2 for i in range(3))
        if dist_bg <= 36:
            c[0], c[1], c[2] = 241, 243, 246

    # 4. Explicitly anchor core design system colors in closest slots
    for target in EXACT_PALETTE_ANCHORS:
        best_idx = 0
        min_dist = float("inf")
        for idx, col in enumerate(palette_colors):
            dist = sum((col[i] - target[i]) ** 2 for i in range(3))
            if dist < min_dist:
                min_dist = dist
                best_idx = idx
        palette_colors[best_idx] = list(target)

    # 5. Build fresh 'P' image to force Pillow to compile an accurate search tree
    flattened = [val for col in palette_colors for val in col]
    fresh_pal_img = Image.new("P", (1, 1))
    fresh_pal_img.putpalette(flattened)
    return fresh_pal_img


def build_optimized_gif(
    frames: list[Image.Image],
    durations: list[int],
    output_path: Path,
) -> int:
    """Compile frames into a single-palette looping GIF without dithering."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Deriving unified color palette from {len(frames)} frames...")
    palette_base = build_unified_palette(frames)

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


def locate_color_in_image(
    img: Image.Image,
    target_rgb: tuple[int, int, int],
    tolerance: int = 1,
) -> tuple[int, int] | None:
    """Find coordinates of the first pixel matching target RGB within tolerance."""
    w, h = img.size
    for y in range(h):
        for x in range(w):
            p = img.getpixel((x, y))
            if (
                isinstance(p, tuple)
                and len(p) >= 3
                and all(abs(p[i] - target_rgb[i]) <= tolerance for i in range(3))
            ):
                return (x, y)
    return None


def verify_color_fidelity(
    gif_path: Path,
    stage_samples: dict[str, Image.Image],
    max_allowed_diff: int = MAX_ALLOWED_COLOR_CHANNEL_DIFF,
) -> list[dict[str, Any]]:
    """Verify color fidelity between raw captured PNGs and the compiled GIF.

    Compares key color points across all storyboard stages:
    - Page background (--bg-canvas #f1f3f6)
    - Panel surface (--bg-surface #ffffff)
    - Bar segment role (--seg-role #1f4e78)
    - Bar segment revenue (--seg-rev #2a757e)
    - Disqualified highlight background (--color-disq-bg #fbe8e8)
    - Disqualified highlight border (--color-disq #8d1d1d)
    - Main text (--text-main #18202b)

    Fails with SystemExit(1) if any channel difference exceeds max_allowed_diff.
    """
    with Image.open(gif_path) as im:
        actual_frames = getattr(im, "n_frames", 1)
        # Map storyboard stages to representative GIF frames:
        # Frame 0 -> Stage A, Frame 3 -> Stage B, Frame 5 -> Stage C, Frame 7 -> Stage D
        stage_frame_indices = {
            "Stage A": 0,
            "Stage B": min(3, actual_frames - 1),
            "Stage C": min(5, actual_frames - 1),
            "Stage D": min(7, actual_frames - 1),
        }

        # Extract RGB images of corresponding GIF frames
        gif_stage_frames: dict[str, Image.Image] = {}
        for stage_name, f_idx in stage_frame_indices.items():
            im.seek(f_idx)
            gif_stage_frames[stage_name] = im.convert("RGB")

    raw_c = stage_samples["Stage C"]
    raw_d = stage_samples["Stage D"]

    # Discover coordinates of elements from raw captured PNGs
    pt_bg = (20, 200)
    pt_surface = (640, 200)
    pt_seg_role = locate_color_in_image(raw_c, (31, 78, 120)) or (848, 282)
    pt_seg_rev = locate_color_in_image(raw_c, (42, 117, 126)) or (506, 396)
    pt_disq_bg = locate_color_in_image(raw_d, (251, 232, 232)) or (63, 181)
    pt_disq_border = locate_color_in_image(raw_d, (141, 29, 29)) or (375, 96)
    pt_text_main = locate_color_in_image(raw_c, (24, 32, 43)) or (42, 23)

    verification_items: list[tuple[str, str, tuple[int, int]]] = [
        ("Fundo da página (canvas)", "Stage A", pt_bg),
        ("Superfície do painel", "Stage A", pt_surface),
        ("Fundo da página (canvas)", "Stage B", pt_bg),
        ("Superfície do painel", "Stage B", pt_surface),
        ("Fundo da página (canvas)", "Stage C", pt_bg),
        ("Superfície da tabela", "Stage C", (100, 150)),
        ("Segmento de barra (cargo)", "Stage C", pt_seg_role),
        ("Segmento de barra (faturamento)", "Stage C", pt_seg_rev),
        ("Texto principal", "Stage C", pt_text_main),
        ("Fundo da página (canvas)", "Stage D", pt_bg),
        ("Fundo do destaque eliminado", "Stage D", pt_disq_bg),
        ("Borda do destaque eliminado", "Stage D", pt_disq_border),
    ]

    print("\n================================================================================")
    print(" VERIFICAÇÃO DE FIDELIDADE DE CORES (TOLERÂNCIA MÁXIMA: 3 POR CANAL)")
    print("================================================================================")
    print(
        f"{'Etapa':<10} | {'Elemento':<32} | {'Esperado (PNG)':<18} | {'GIF':<18} | {'Diff':<12} | {'Status'}"
    )
    print("-" * 105)

    results: list[dict[str, Any]] = []
    has_failure = False

    for label, stage, coord in verification_items:
        raw_img = stage_samples[stage]
        gif_img = gif_stage_frames[stage]

        raw_color_raw = raw_img.getpixel(coord)
        gif_color_raw = gif_img.getpixel(coord)

        if not isinstance(raw_color_raw, tuple) or not isinstance(gif_color_raw, tuple):
            continue

        raw_rgb = (raw_color_raw[0], raw_color_raw[1], raw_color_raw[2])
        gif_rgb = (gif_color_raw[0], gif_color_raw[1], gif_color_raw[2])

        diffs = [abs(raw_rgb[i] - gif_rgb[i]) for i in range(3)]
        max_d = max(diffs)
        status = "APROVADO" if max_d <= max_allowed_diff else "FALHA"

        if max_d > max_allowed_diff:
            has_failure = True

        entry = {
            "stage": stage,
            "label": label,
            "coord": coord,
            "expected": raw_rgb,
            "obtained": gif_rgb,
            "diff": diffs,
            "max_diff": max_d,
            "status": status,
        }
        results.append(entry)

        print(
            f"{stage:<10} | {label:<32} | {str(raw_rgb):<18} | {str(gif_rgb):<18} | {str(diffs):<12} | {status}"
        )

    print("================================================================================\n")

    if has_failure:
        print(
            f"ERRO: A verificação de fidelidade de cores FALHOU (diferença máxima > {max_allowed_diff})."
        )
        sys.exit(1)

    print(
        "SUCESSO: Todos os pontos de cores-chave atendem ao critério de fidelidade (máx diff <= 3)."
    )
    return results


def main() -> None:
    """Main execution entrypoint."""
    print("================================================================================")
    print(" Recording B2B Lead Qualifier Demo GIF (1280x720 - MedianCut & Fidelity)")
    print("================================================================================")
    frames, durations, stage_samples = asyncio.run(record_frames())
    size_bytes = build_optimized_gif(frames, durations, OUTPUT_PATH)

    if size_bytes > 5 * 1024 * 1024:
        raise ValueError(f"GIF size ({size_bytes} bytes) exceeds 5 MB limit!")

    with Image.open(OUTPUT_PATH) as im:
        actual_frames: int = getattr(im, "n_frames", 1)

    print(f"GIF compiled: {size_bytes} bytes, {actual_frames} frames in file.")
    verify_color_fidelity(OUTPUT_PATH, stage_samples)


if __name__ == "__main__":
    main()
