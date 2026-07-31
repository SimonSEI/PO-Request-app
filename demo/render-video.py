#!/usr/bin/env python3
"""
Render demo/office-app-demo.html to an MP4.

The reel exposes window.__reel.frame(seconds) in #render mode, which paints one
exact frame with no dependence on the wall clock. This walks the timeline at a
fixed frame rate, screenshots each frame, and pipes them straight into ffmpeg —
so the output is frame-accurate rather than a screen recording.

    pip install playwright imageio-ffmpeg
    python3 demo/render-video.py --out demo/office-app-demo.mp4

Options: --fps, --scale (device pixel ratio; 1.5 gives 1080p), --crf, --out.
"""
import argparse, os, subprocess, sys, time
from pathlib import Path

BASE_W, BASE_H = 1280, 720          # design size; scale lifts it to the output size
HEAD = ('<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head><body>')


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument("--src", default=str(here / "office-app-demo.html"))
    ap.add_argument("--out", default=str(here / "office-app-demo.mp4"))
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--quality", type=int, default=92, help="JPEG quality per frame")
    ap.add_argument("--lead", type=float, default=1.0, help="seconds held on the title")
    ap.add_argument("--tail", type=float, default=2.5, help="seconds held on the last shot")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright
    import imageio_ffmpeg

    # The artifact file is a fragment (no <html>/<head>) — wrap it to load locally.
    page_html = Path(a.src).read_text()
    tmp = Path(a.out).with_suffix(".render.html")
    tmp.write_text(HEAD + page_html + "</body></html>")

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out_w, out_h = int(BASE_W * a.scale), int(BASE_H * a.scale)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg, "-y", "-f", "image2pipe", "-framerate", str(a.fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf),
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-s", f"{out_w}x{out_h}", a.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    shot_count = dup_count = 0
    started = time.time()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium"))
            pg = browser.new_page(viewport={"width": BASE_W, "height": BASE_H},
                                  device_scale_factor=a.scale)
            pg.goto(tmp.resolve().as_uri() + "#render")
            pg.wait_for_function("window.__reel && window.__reel.total > 0", timeout=30000)
            pg.wait_for_timeout(700)          # let fonts and first paint settle
            total = pg.evaluate("window.__reel.total")
            frames = int((a.lead + total + a.tail) * a.fps)
            print(f"reel {total:.0f}s → {frames} frames at {a.fps}fps, {out_w}x{out_h}",
                  flush=True)

            last_sig, last_bytes = None, None
            for i in range(frames):
                t = min(max(i / a.fps - a.lead, 0.0), total - 0.001)
                sig = pg.evaluate("t => window.__reel.frame(t)", t)
                if sig == last_sig and last_bytes is not None:
                    dup_count += 1                      # pixel-identical, reuse
                else:
                    last_bytes = pg.screenshot(type="jpeg", quality=a.quality)
                    last_sig = sig
                    shot_count += 1
                proc.stdin.write(last_bytes)
                if i % (a.fps * 15) == 0:
                    el = time.time() - started
                    pct = (i + 1) / frames
                    eta = el / pct - el if pct else 0
                    print(f"  {pct:5.1%}  frame {i}/{frames}  "
                          f"captured {shot_count} reused {dup_count}  eta {eta/60:.1f}m",
                          flush=True)
            browser.close()
    finally:
        if proc.stdin:
            proc.stdin.close()
        err = proc.stderr.read().decode()[-1500:]
        if proc.wait() != 0:
            print(err, file=sys.stderr)
            sys.exit("ffmpeg failed")
        tmp.unlink(missing_ok=True)

    size = Path(a.out).stat().st_size / 1e6
    print(f"\n{a.out}  {size:.1f} MB  "
          f"({shot_count} captured, {dup_count} reused, "
          f"{(time.time()-started)/60:.1f} min)")


if __name__ == "__main__":
    main()
