"""Record the running Parcel Math demo. Requires Chromium, Playwright, Pillow and ffmpeg."""
import argparse
from io import BytesIO
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright


WIDTH = 1440
SCREEN_HEIGHT = 694
HEIGHT = 810
FPS = 15
VIEWPORT = {"width": WIDTH, "height": SCREEN_HEIGHT}
DEFAULT_OUTPUT = Path(__file__).with_name("parcel-math.mp4")


def font(size, weight):
    paths = [
        f"/usr/share/fonts/truetype/open-sans/OpenSans-{weight}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if weight == 'Bold' else ''}.ttf",
    ]
    return ImageFont.truetype(next(path for path in paths if Path(path).is_file()), size)


def cursor_image():
    size = 4
    cursor = Image.new("RGBA", (28 * size, 36 * size))
    points = [(2, 2), (2, 27), (9, 21), (15, 33), (21, 30), (15, 19), (26, 18)]
    points = [(x * size, y * size) for x, y in points]
    draw = ImageDraw.Draw(cursor)
    draw.polygon(points, fill="#ffffff")
    draw.line(points + [points[0]], fill="#111827", width=2 * size, joint="curve")
    return cursor.resize((28, 36), Image.Resampling.LANCZOS)


class Recording:
    def __init__(self, output):
        self.encoder = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe",
             "-framerate", str(FPS), "-vcodec", "mjpeg", "-i", "-", "-threads", "2",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
             "-r", "30", "-movflags", "+faststart", str(output)], stdin=subprocess.PIPE,
        )
        self.canvas = Image.new("RGB", (WIDTH, HEIGHT))
        self.pointer = cursor_image()
        self.xy = (0, 0)
        self.show_cursor = False
        self.frames = 0
        self.page = None

    def caption(self, label, message):
        panel = Image.new("RGB", (WIDTH, HEIGHT - SCREEN_HEIGHT), "#142527")
        draw = ImageDraw.Draw(panel)
        draw.rectangle((0, 0, WIDTH, 2), fill="#85c6ac")
        draw.text((43, 17), label.upper(), font=font(17, "Bold"), fill="#a6e0c6")
        face = font(31, "Semibold")
        while draw.textlength(message, font=face) > WIDTH - 86:
            face = font(face.size - 1, "Semibold")
        draw.text((42, 45), message, font=face, fill="#fafaf4")
        self.panel = panel

    def frame(self):
        raw = self.page.screenshot(type="jpeg", quality=94, timeout=10000)
        with Image.open(BytesIO(raw)) as screen:
            self.canvas.paste(screen, (0, 0))
        if self.show_cursor:
            self.canvas.paste(self.pointer, self.xy, self.pointer)
        self.canvas.paste(self.panel, (0, SCREEN_HEIGHT))
        self.canvas.save(self.encoder.stdin, format="JPEG", quality=94, subsampling=0)
        self.frames += 1

    def hold(self, seconds):
        for _ in range(round(seconds * FPS)):
            started = time.monotonic()
            self.frame()
            time.sleep(max(0, 1 / FPS - (time.monotonic() - started)))

    def point(self, locator, click=False):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        if box is None:
            raise RuntimeError("The target is not visible")
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        x0, y0 = self.xy if self.show_cursor else (max(10, x - 150), min(y + 80, SCREEN_HEIGHT - 50))
        self.show_cursor = True
        for n in range(1, 12):
            t = (1 - math.cos(n / 11 * math.pi)) / 2
            self.xy = (round(x0 + t * (x - x0)), round(y0 + t * (y - y0)))
            self.page.mouse.move(*self.xy)
            self.frame()
        if click:
            self.page.mouse.down()
            self.frame()
            self.page.mouse.up()
            self.hold(.25)

    def finish(self):
        self.encoder.stdin.close()
        if self.encoder.wait() != 0:
            raise RuntimeError("ffmpeg failed")


def capture(browser, base, clip):
    def checkout(variant):
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1, locale="en-IE")
        page = context.new_page()
        with page.expect_response(lambda response: "/api/visit?demo=" + variant in response.url) as assigned:
            page.goto(base + "/?demo=" + variant)
        payload = assigned.value.json()
        if payload["variant"] != variant or payload["scenario"]["itemCents"] != 3080:
            raise RuntimeError(f"Missing expected assignment or basket for {variant}")
        page.locator("#checkout").wait_for(state="visible")
        if page.locator("#cap").inner_text() != "€35.00":
            raise RuntimeError("The recorded basket requires the €35.00 scenario.")
        clip.page = page
        clip.show_cursor = False
        return context, page

    control, page = checkout("standard")
    clip.caption("SDK walkthrough / Control", "Can a €30.80 order stay within a €35 budget after delivery?")
    clip.hold(3.3)
    clip.caption("SDK walkthrough / Control", "The control shows shipping fees. Priority adds €4.45.")
    clip.point(page.locator("label.option").filter(has_text="Priority"), click=True)
    if page.locator("#estimate").inner_text() != "€35.25":
        raise RuntimeError("Unexpected Priority total.")
    clip.hold(2.2)
    clip.caption("SDK walkthrough / Control", "Selecting Priority reveals a €35.25 total, just over budget.")
    clip.point(page.locator("#estimate"))
    clip.hold(2.4)
    control.close()

    treatment, page = checkout("landed")
    clip.caption("SDK walkthrough / Treatment", "The treatment shows each full order total before you choose.")
    clip.hold(3.2)
    clip.point(page.locator("label.option").filter(has_text="Economy"), click=True)
    clip.caption("SDK walkthrough / Treatment", "Economy is the fastest option within this budget.")
    clip.hold(1.8)
    clip.point(page.locator("#confirm"), click=True)
    result = page.locator("#result")
    result.wait_for(state="visible")
    if "€32.75" not in result.inner_text() or "€2.25 under budget" not in result.inner_text():
        raise RuntimeError("Checkout confirmation did not match the example basket.")
    result.scroll_into_view_if_needed()
    clip.show_cursor = False
    clip.caption("First confirmed choice", "Economy delivers for €32.75, with €2.25 of the budget left.")
    clip.hold(3.4)
    treatment.close()

    results = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
    page = results.new_page()
    clip.page = page
    page.goto(base + "/native-results")
    page.locator("table tbody tr").first.wait_for()
    body = page.locator("body").inner_text().lower()
    if "synthetic traffic" not in body or "recorded native platform run" not in body:
        raise RuntimeError("Result screen must be the native synthetic run.")
    response = page.request.get(base + "/api/native-results")
    if not response.ok:
        raise RuntimeError(f"Native experiment export unavailable ({response.status}).")
    export = response.json()
    native = export["metrics"]["first_choice_within_budget"]["arms"]
    report = export["app_readout"]
    control, treatment = native["control"], native["landed"]
    for displayed, observed in [(report["arms"]["standard"], control),
                                (report["arms"]["landed"], treatment)]:
        if (displayed["within"], displayed["exposed"]) != (observed["converted"], observed["exposed"]):
            raise RuntimeError("The readout disagrees with the native Flagsmith metrics.")
    sample = control["exposed"] + treatment["exposed"]
    if sample != report["sampleSize"] or report["delta"] is None:
        raise RuntimeError("A full native reference run is required.")
    label = f"Flagsmith {export['flagsmith_version']} / PostgreSQL"
    clip.caption(label, f"{sample} simulated visits. Success means the first confirmed choice fit the budget.")
    clip.hold(3.7)
    clip.caption("Native experiment / Within budget",
                 f"Fees {control['converted']}/{control['exposed']}, "
                 f"totals {treatment['converted']}/{treatment['exposed']}. "
                 f"The difference was {100*report['delta']:+.1f} percentage points.")
    page.locator("table").first.scroll_into_view_if_needed()
    clip.hold(4.0)
    control_rate = 100 * control["converted"] / control["exposed"]
    treatment_rate = 100 * treatment["converted"] / treatment["exposed"]
    clip.caption("Simulated first-choice accuracy",
                 f"{control_rate:.1f}% with fees, {treatment_rate:.1f}% with totals. Real shopper behavior is unmeasured.")
    page.locator("p.note").last.scroll_into_view_if_needed()
    clip.hold(4.4)
    results.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--chromium", default=shutil.which("chromium"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temp, sync_playwright() as pw:
        staged = Path(temp) / "capture.mp4"
        clip = Recording(staged)
        try:
            browser = pw.chromium.launch(executable_path=args.chromium, headless=True,
                                         args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
            capture(browser, args.base_url.rstrip("/"), clip)
            browser.close()
        except BaseException:
            clip.encoder.terminate()
            clip.encoder.wait()
            raise
        clip.finish()
        staged.replace(args.output)
        print(f"{args.output} ({clip.frames/FPS:.1f} seconds)")


if __name__ == "__main__":
    main()
