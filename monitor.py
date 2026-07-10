#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

URL = "https://www.the-fizz.com/en/search-nl/?searchcriteria=BUILDING:THE_FIZZ_LEIDEN;AREA:LEIDEN;"
ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "profile"
EXT = ROOT / "extensions" / "buster"
HEADLESS = os.environ.get("HEADLESS", "0") == "1"
STRICT = os.environ.get("STRICT", "0") == "1"
DEBUG_DIR = Path(os.environ.get("DEBUG_DIR", str(ROOT)))
# The gate page shows this button; its presence in the final scrape means we
# never made it past the reCAPTCHA interstitial.
GATE_MARKER = re.compile(r"Weiter zur Buchung", re.I)

KEYWORDS = [
    "fully booked",
    "ausgebucht",
    "Letting Team",
    "availability",
    "Reservations",
    "currently",
    "verfügbar",
    "available",
]


def dump_debug(page) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / "debug.png"), full_page=True)
        for i, frame in enumerate(page.frames):
            try:
                content = frame.content()
                (DEBUG_DIR / f"debug-frame-{i}.html").write_text(
                    f"<!-- frame url: {frame.url} -->\n{content[:80000]}"
                )
            except Exception:
                pass
    except Exception as e:
        print(f"WARN: debug capture failed: {e}", file=sys.stderr)


def dismiss_consent(page) -> None:
    """Close the Borlabs cookie-consent modal a fresh profile gets served.

    It overlays the whole page and swallows clicks meant for the reCAPTCHA.
    Prefer essential-only; the captcha widget renders before consent anyway.
    """
    dialog = page.locator("#BorlabsCookieBox")
    try:
        dialog.wait_for(state="visible", timeout=5000)
    except Exception:
        return
    for pattern in (r"nur essenzielle|only essential|essential only",
                    r"akzeptiere alle|accept all",
                    r"einwilligung speichern|save consent"):
        try:
            dialog.locator("button, a[role='button']").filter(
                has_text=re.compile(pattern, re.I)
            ).first.click(timeout=4000)
            page.wait_for_timeout(2000)
            print(f"INFO: consent dismissed via /{pattern}/", file=sys.stderr)
            return
        except Exception:
            continue
    dump_debug(page)
    print("WARN: consent box visible but no known button matched",
          file=sys.stderr)


def captcha_token_present(page) -> bool:
    try:
        return page.evaluate("""
            () => {
                const t = document.querySelector(
                    'textarea[name="g-recaptcha-response"]');
                return !!(t && t.value && t.value.length > 0);
            }
        """)
    except Exception:
        return False


def main() -> None:
    with sync_playwright() as pw:
        args = ["--disable-blink-features=AutomationControlled"]
        if not os.environ.get("CI"):
            # Keep the window out of sight locally; under xvfb this would
            # push it off the virtual screen and break Buster's clicks.
            args.append("--window-position=4000,4000")
        if EXT.exists():
            args += [
                f"--load-extension={EXT}",
                f"--disable-extensions-except={EXT}",
            ]

        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            headless=HEADLESS,
            viewport={"width": 1280, "height": 900},
            args=args,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        dismiss_consent(page)

        solved = captcha_token_present(page)
        if not solved:
            try:
                anchor = page.frame_locator(
                    "iframe[src*='recaptcha'][src*='anchor']"
                )
                anchor.locator(".recaptcha-checkbox-border").click(timeout=15000)
                page.wait_for_timeout(3000)
            except PWTimeout:
                print("WARN: no reCAPTCHA checkbox found (already solved?)",
                      file=sys.stderr)
            solved = captcha_token_present(page)

        if not solved:
            buster_clicked = False
            solver = None
            solver_frame = None
            # Buster may inject into bframe, a nested iframe, or directly under
            # <html> — search every frame on the page.
            for _ in range(15):
                for frame in page.frames:
                    try:
                        loc = frame.locator(
                            'button[title="Solve the challenge"], #solver-button'
                        ).first
                        if loc.count() > 0:
                            solver = loc
                            solver_frame = frame
                            break
                    except Exception:
                        continue
                if solver is not None:
                    break
                page.wait_for_timeout(1000)

            if solver is not None:
                print(f"INFO: Buster button found in frame: {solver_frame.url}",
                      file=sys.stderr)
                try:
                    solver.scroll_into_view_if_needed(timeout=3000)
                except Exception:
                    pass
                try:
                    solver.click(force=True, timeout=5000)
                    buster_clicked = True
                except Exception:
                    try:
                        solver.dispatch_event("click")
                        buster_clicked = True
                    except Exception as e:
                        print(f"WARN: Buster click failed: {e}", file=sys.stderr)

            if buster_clicked:
                # Poll for the actual success signal instead of a blind wait;
                # Buster's audio round-trip regularly needs 20-60s.
                for i in range(12):
                    page.wait_for_timeout(5000)
                    if captcha_token_present(page):
                        solved = True
                        print(f"INFO: captcha solved after ~{(i + 1) * 5}s",
                              file=sys.stderr)
                        break
                if not solved:
                    print("WARN: captcha token never appeared after Buster click",
                          file=sys.stderr)
            else:
                dump_debug(page)
                print("WARN: Buster button not found — see debug.png and "
                      "debug-frame-*.html", file=sys.stderr)

        try:
            page.locator("button, a").filter(
                has_text=GATE_MARKER
            ).first.click(timeout=10000)
            page.wait_for_timeout(5000)
        except PWTimeout:
            pass

        text = page.locator("body").inner_text()

        # The healthy post-gate page (fully-booked notice OR room listings)
        # never shows the gate button; if it is still there the CAPTCHA won.
        if STRICT and (not text.strip() or GATE_MARKER.search(text)):
            dump_debug(page)
            print("ERROR: still on the reCAPTCHA gate page — scrape failed",
                  file=sys.stderr)
            ctx.close()
            sys.exit(2)

        ctx.close()

    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if s and any(k.lower() in s.lower() for k in KEYWORDS):
            lines.append(s)

    result = " | ".join(lines) if lines else text[:600].strip()
    result = re.sub(r"\s+", " ", result)
    print(result)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
