"""
Audit logger for LinkedIn connection automation.

Creates one log file per run inside logs/ named:
    logs/YYYY-MM-DD_HH-MM-SS_<vanity-name>.log

Each section is clearly delimited so logs are easy to grep and read.
"""

import json
import textwrap
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"
ERROR_LOGS_DIR = Path(__file__).parent.parent / "error_logs"


class AuditLogger:
    def __init__(self, vanity_name: str | None, profile_url: str):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ERROR_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        slug = vanity_name or "unknown"
        self._ts = ts
        self._slug = slug
        self._path = LOGS_DIR / f"{ts}_{slug}.log"
        self._f = self._path.open("w", encoding="utf-8")
        self._write_header(profile_url, vanity_name, ts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def profile_state(self, state: str) -> None:
        self._section("PROFILE STATE CHECK")
        self._line(f"state = {state}")

    def strategy_start(self, name: str) -> None:
        self._section(f"STRATEGY: {name.upper()}")

    def selector_tried(self, selector: str, hit: bool) -> None:
        mark = "HIT " if hit else "MISS"
        self._line(f"[{mark}] {selector}")

    def strategy_result(self, name: str, success: bool) -> None:
        self._line(f"→ {'PASSED' if success else 'FAILED'} ({name})")

    def llm_elements(self, elements: list[dict]) -> None:
        self._section("LLM INPUT — ELEMENTS SENT")
        self._line(f"count = {len(elements)}")
        self._raw(json.dumps(elements, indent=2))

    def llm_prompt(self, prompt: str) -> None:
        self._section("LLM INPUT — FINAL PROMPT")
        self._raw(prompt)

    def llm_response_raw(self, raw: str) -> None:
        self._section("LLM OUTPUT — RAW RESPONSE")
        self._raw(raw)

    def llm_response_parsed(self, parsed: dict | None) -> None:
        self._section("LLM OUTPUT — PARSED RESULT")
        self._raw(json.dumps(parsed, indent=2) if parsed else "null (parse failed)")

    def post_click(self, action: str) -> None:
        self._section("POST-CLICK")
        self._line(action)

    def success_detection(self, method: str, result: bool) -> None:
        self._section("SUCCESS DETECTION")
        self._line(f"method  = {method}")
        self._line(f"result  = {'SUCCESS' if result else 'FAILURE'}")

    def final_result(self, status: str) -> None:
        self._section("FINAL RESULT")
        self._line(f"status = {status.upper()}")
        self._divider()
        self._f.flush()

    async def capture_error(self, page, label: str = "error") -> None:
        """
        Save a screenshot and the <main> HTML to error_logs/ for debugging.
        Call this whenever the automation hits a failure path.
        """
        base = ERROR_LOGS_DIR / f"{self._ts}_{self._slug}_{label}"
        screenshot_path = base.with_suffix(".png")
        html_path = base.with_suffix(".html")

        try:
            await page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception as e:
            screenshot_path = None
            self._line(f"[capture_error] Screenshot failed: {e}")

        try:
            main = page.locator("main")
            count = await main.count()
            if count > 0:
                html = await main.first.inner_html()
                html_path.write_text(f"<!-- <main> HTML captured at {label} -->\n<main>\n{html}\n</main>\n", encoding="utf-8")
            else:
                html = await page.content()
                html_path.write_text(html, encoding="utf-8")
        except Exception as e:
            html_path = None
            self._line(f"[capture_error] HTML capture failed: {e}")

        self._section(f"ERROR CAPTURE — {label.upper()}")
        if screenshot_path:
            self._line(f"screenshot = {screenshot_path}")
        if html_path:
            self._line(f"html       = {html_path}")
        self._f.flush()

    def close(self) -> None:
        self._f.close()

    @property
    def path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_header(self, profile_url: str, vanity_name: str | None, ts: str) -> None:
        self._divider()
        self._line(f"LinkedIn Connection Audit Log")
        self._line(f"timestamp   = {ts}")
        self._line(f"profile_url = {profile_url}")
        self._line(f"vanity_name = {vanity_name or 'unknown'}")
        self._divider()

    def _section(self, title: str) -> None:
        self._f.write(f"\n{'─' * 60}\n{title}\n{'─' * 60}\n")

    def _divider(self) -> None:
        self._f.write(f"{'═' * 60}\n")

    def _line(self, text: str) -> None:
        self._f.write(text + "\n")

    def _raw(self, text: str) -> None:
        self._f.write(textwrap.indent(text, "  ") + "\n")
