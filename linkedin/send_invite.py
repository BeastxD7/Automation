"""
LinkedIn send_invite — sends a connection invite to a profile URL.

Strategy order (fast → slow):
  1. Direct Connect button (hardcoded selectors)
  2. More dropdown → Connect (hardcoded selectors)
  3. LLM analyzer via Ollama (last resort, when selectors fail)

Usage:
    async with get_linkedin_context() as (browser, page):
        success = await send_invite(page, "https://www.linkedin.com/in/someprofile/")
"""

import asyncio
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    Page,
    TimeoutError as PWTimeout,
)
from contextlib import asynccontextmanager

from linkedin.selectors import (
    CONNECT_BUTTON_ARIA,
    ADD_BUTTON_ARIA,
    ADD_BUTTON_TEXT,
    CONNECT_LINK_ARIA,
    CONNECT_LINK_HREF,
    MORE_BUTTON_SELECTORS,
    CONNECT_IN_DROPDOWN,
    DROPDOWN_CONTAINER_SELECTORS,
    MODAL_SEND_WITHOUT_NOTE,
    MODAL_CONNECT_BUTTON,
    SUCCESS_TOAST,
    ERROR_TOAST,
    SIGNUP_MODAL_CLOSE,
    SIGNUP_PAGE_INDICATORS,
    PENDING_SELECTORS,
    ALREADY_CONNECTED_SELECTORS,
    INVITE_LIMIT_INDICATORS,
    FOLLOW_ONLY_INDICATORS,
)
from linkedin.analyzer import analyze_connect_button, get_element_locator, _is_blocked
from linkedin.audit import AuditLogger

SESSION_DIR = Path(__file__).parent.parent / ".linkedin_session"
FAST_TIMEOUT = 3_000
SLOW_TIMEOUT = 8_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_invite(page: Page, profile_url: str, force_llm: bool = False) -> str:
    """
    Navigate to a LinkedIn profile and send a connection invite.

    Returns one of:
      "sent"      — invite successfully sent
      "pending"   — invite already sent, awaiting acceptance
      "connected" — already connected, no action needed
      "failed"    — could not send (auth wall, selectors broke, etc.)

    force_llm=True skips hardcoded strategies and goes straight to the LLM analyzer.
    """
    vanity_name = _extract_vanity_name(profile_url)
    audit = AuditLogger(vanity_name=vanity_name, profile_url=profile_url)

    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=20_000)
        await _wait_for_profile_load(page)
    except Exception as e:
        print(f"[send_invite] Navigation failed: {e}")
        audit.final_result("failed")
        audit.close()
        return "failed"

    # Must handle popup before anything else — it blocks all interactions
    if not await _handle_auth_wall(page):
        audit.final_result("failed")
        audit.close()
        return "failed"

    # Check profile state before attempting any strategy
    state = await _check_profile_state(page)
    audit.profile_state(state)
    if state == "pending":
        print("[send_invite] Invite already pending — skipping.")
        audit.final_result("pending")
        audit.close()
        return "pending"
    if state == "connected":
        print("[send_invite] Already connected — skipping.")
        audit.final_result("connected")
        audit.close()
        return "connected"

    # Check for weekly invite limit before attempting anything
    for selector in INVITE_LIMIT_INDICATORS:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=2_000)
            print("[send_invite] Weekly invitation limit reached.")
            audit.final_result("limit_reached")
            audit.close()
            return "limit_reached"
        except PWTimeout:
            continue

    # Check for follow-only profiles (no Connect option exists at all)
    main = page.locator("main")
    has_connect = await main.locator(
        'a[href*="/preload/custom-invite/"], button[aria-label*="Connect"], button[aria-label*="Add"], button[aria-label="More"]'
    ).count() > 0
    if not has_connect:
        for selector in FOLLOW_ONLY_INDICATORS:
            try:
                await main.locator(selector).first.wait_for(state="visible", timeout=2_000)
                print("[send_invite] Follow-only profile — no Connect option available.")
                audit.final_result("follow_only")
                audit.close()
                return "follow_only"
            except PWTimeout:
                continue

    status = "failed"

    if not force_llm:
        # Strategy 1: direct Connect button
        audit.strategy_start("direct_connect")
        try:
            if await _strategy_direct_connect(page, vanity_name, audit=audit):
                result = await _handle_post_click(page, audit=audit)
                audit.strategy_result("direct_connect", result)
                status = "sent" if result else "failed"
                audit.final_result(status)
                audit.close()
                return status
        except Exception as e:
            print(f"[send_invite] direct_connect raised: {e}")
        audit.strategy_result("direct_connect", False)

        # Strategy 2: More dropdown
        audit.strategy_start("more_dropdown")
        try:
            if await _strategy_more_dropdown(page, audit=audit):
                result = await _handle_post_click(page, audit=audit)
                audit.strategy_result("more_dropdown", result)
                status = "sent" if result else "failed"
                audit.final_result(status)
                audit.close()
                return status
        except Exception as e:
            print(f"[send_invite] more_dropdown raised: {e}")
        audit.strategy_result("more_dropdown", False)
    else:
        print("[send_invite] Skipping hardcoded strategies (--force-llm).")

    # Strategy 3: LLM analyzer
    audit.strategy_start("llm_analyzer")
    print("[send_invite] Falling back to LLM analyzer.")
    try:
        if await _strategy_llm_analyzer(page, vanity_name=vanity_name, audit=audit):
            result = await _handle_post_click(page, audit=audit)
            audit.strategy_result("llm_analyzer", result)
            status = "sent" if result else "failed"
            audit.final_result(status)
            audit.close()
            return status
    except Exception as e:
        print(f"[send_invite] llm_analyzer raised: {e}")
    audit.strategy_result("llm_analyzer", False)

    print("[send_invite] All strategies exhausted.")
    audit.final_result("failed")
    audit.close()
    return "failed"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@asynccontextmanager
async def get_linkedin_context(headless: bool = False):
    """
    Persistent browser context — LinkedIn session survives across runs.
    First run: log in manually in the opened browser window.
    Subsequent runs: session is reused automatically.
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        try:
            yield browser, page
        finally:
            await browser.close()


# ---------------------------------------------------------------------------
# Auth wall / signup popup handler
# ---------------------------------------------------------------------------

async def _handle_auth_wall(page: Page) -> bool:
    """
    Detect and dismiss LinkedIn's signup/login popup or redirect.
    Returns False if we're fully redirected to a login page (not recoverable).
    Returns True if the profile page is accessible.
    """
    await asyncio.sleep(1)  # let any modal animate in

    # Check if page redirected entirely to signup/login
    current_url = page.url
    if "linkedin.com/login" in current_url or "linkedin.com/signup" in current_url:
        print("[auth_wall] Redirected to login page — not logged in. Please log in first.")
        return False

    # Check for signup indicators in page content
    for selector in SIGNUP_PAGE_INDICATORS:
        try:
            el = page.locator(selector).first
            await el.wait_for(state="visible", timeout=1_500)
            print(f"[auth_wall] Login/signup wall detected ({selector}) — not logged in.")
            return False
        except PWTimeout:
            continue

    # Try to dismiss a modal popup (softer version — modal over the profile)
    for selector in SIGNUP_MODAL_CLOSE:
        try:
            btn = page.locator(selector).first
            await btn.wait_for(state="visible", timeout=1_500)
            await btn.click()
            print(f"[auth_wall] Dismissed signup modal via: {selector}")
            await asyncio.sleep(0.5)
            return True
        except PWTimeout:
            continue

    # Also try Escape key as a catch-all modal dismissal
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.3)

    return True


# ---------------------------------------------------------------------------
# Strategy 1: Direct Connect button
# ---------------------------------------------------------------------------

async def _strategy_direct_connect(
    page: Page,
    vanity_name: str | None = None,
    audit: "AuditLogger | None" = None,
) -> bool:
    main = page.locator("main")

    if vanity_name:
        targeted = f'a[href*="vanityName={vanity_name}"]'
        try:
            btn = main.locator(targeted).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print(f"[direct_connect] Clicked via vanity-name href ({vanity_name})")
            if audit:
                audit.selector_tried(targeted, hit=True)
            return True
        except PWTimeout:
            if audit:
                audit.selector_tried(targeted, hit=False)

    # Precise selectors — href and aria-label patterns unlikely to match sidebar cards
    for selector in [CONNECT_LINK_HREF, CONNECT_LINK_ARIA]:
        try:
            btn = main.locator(selector).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print(f"[direct_connect] Clicked via: {selector}")
            if audit:
                audit.selector_tried(selector, hit=True)
            return True
        except PWTimeout:
            if audit:
                audit.selector_tried(selector, hit=False)
            continue

    # aria-label partial-match selectors — scoped to the profile header section.
    # NOTE: text-based selectors (a:has-text, button:has-text) are intentionally
    # excluded here because Playwright's :has-text() is case-insensitive and will
    # match "mutual connection" links, navigating to the wrong page.
    header = await _find_profile_header_section(page)
    if header is None:
        return False

    for selector in [CONNECT_BUTTON_ARIA, ADD_BUTTON_ARIA, ADD_BUTTON_TEXT]:
        try:
            btn = header.locator(selector).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print(f"[direct_connect] Clicked via (header-scoped): {selector}")
            if audit:
                audit.selector_tried(selector, hit=True)
            return True
        except PWTimeout:
            if audit:
                audit.selector_tried(selector, hit=False)
            continue
    return False


# ---------------------------------------------------------------------------
# Robust click — falls back to JS dispatch when an overlay intercepts
# ---------------------------------------------------------------------------

async def _robust_click(page: Page, locator) -> None:
    """
    Try a normal Playwright click first. If an overlay is intercepting pointer
    events (common with LinkedIn's cookie/notification bars), fall back to a
    direct JavaScript click which bypasses the overlay check.
    """
    try:
        await locator.click(timeout=FAST_TIMEOUT)
    except Exception:
        print("[robust_click] Normal click intercepted — using JS click fallback.")
        await locator.evaluate("el => el.click()")


# ---------------------------------------------------------------------------
# Shared: click Connect inside an open dropdown, scoped to the container
# ---------------------------------------------------------------------------

async def _click_connect_in_dropdown(page: Page, vanity_name: str | None = None) -> bool:
    """
    After the More button is clicked and the dropdown is open, find and click
    the Connect/Add option.

    Scopes the search to the dropdown container element first
    (e.g. .artdeco-dropdown__content, [role="menu"]) so that broad text
    selectors like span:has-text("Connect") can't accidentally match sidebar
    suggestion cards or other parts of the page.
    """
    # Find the open dropdown container
    container = None
    for sel in DROPDOWN_CONTAINER_SELECTORS:
        try:
            candidate = page.locator(sel).first
            await candidate.wait_for(state="visible", timeout=FAST_TIMEOUT)
            container = candidate
            print(f"[dropdown] Container found via: {sel}")
            break
        except PWTimeout:
            continue

    if container is None:
        # No recognisable container — fall back to unscoped but only use
        # aria-label selectors (never bare text matches) to reduce false-positive risk
        print("[dropdown] No container found — trying aria-label selectors only.")
        for selector in ['div[aria-label*="Connect"]', 'div[aria-label*="Add"]']:
            try:
                opt = page.locator(selector).first
                await opt.wait_for(state="visible", timeout=FAST_TIMEOUT)
                await opt.click()
                return True
            except PWTimeout:
                continue
        return False

    # Most precise: vanity-name scoped link inside the container
    if vanity_name:
        targeted = f'a[href*="vanityName={vanity_name}"]'
        try:
            opt = container.locator(targeted).first
            await opt.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await opt.click()
            print(f"[dropdown] Clicked Connect via vanity-name href ({vanity_name})")
            return True
        except PWTimeout:
            pass

    # Scoped fallback selectors inside the container
    for selector in CONNECT_IN_DROPDOWN:
        try:
            opt = container.locator(selector).first
            await opt.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await opt.click()
            print(f"[dropdown] Clicked Connect via: {selector}")
            return True
        except PWTimeout:
            continue

    return False


# ---------------------------------------------------------------------------
# Strategy 2: More dropdown → Connect
# ---------------------------------------------------------------------------

async def _strategy_more_dropdown(page: Page, audit: "AuditLogger | None" = None) -> bool:
    more_btn = None
    for selector in MORE_BUTTON_SELECTORS:
        try:
            candidate = page.locator(selector).first
            await candidate.wait_for(state="visible", timeout=FAST_TIMEOUT)
            more_btn = candidate
            if audit:
                audit.selector_tried(selector, hit=True)
            break
        except PWTimeout:
            if audit:
                audit.selector_tried(selector, hit=False)
            continue

    if more_btn is None:
        return False

    await _robust_click(page, more_btn)
    await asyncio.sleep(0.5)

    if await _click_connect_in_dropdown(page, vanity_name=None):
        print("[more_dropdown] Clicked Connect inside dropdown.")
        return True

    await page.keyboard.press("Escape")
    return False


# ---------------------------------------------------------------------------
# Strategy 3: LLM analyzer (Ollama)
# ---------------------------------------------------------------------------

async def _strategy_llm_analyzer(
    page: Page,
    vanity_name: str | None = None,
    audit: "AuditLogger | None" = None,
) -> bool:
    analysis = await analyze_connect_button(page, vanity_name=vanity_name, audit=audit)
    if not analysis:
        return False

    strategy = analysis.get("strategy")
    print(f"[llm_analyzer] strategy={strategy}, confidence={analysis.get('confidence')}, label='{analysis.get('label')}', notes='{analysis.get('notes')}'")

    if strategy == "direct":
        element = analysis.get("element")
        if not element:
            return False
        # Hard safety check — refuse to click Follow/Message/Unfollow even if LLM says to
        if _is_blocked(element):
            print(f"[llm_analyzer] BLOCKED: LLM picked a forbidden element "
                  f"('{element.get('text') or element.get('ariaLabel')}') — aborting.")
            return False
        locator = await get_element_locator(page, element)
        await locator.wait_for(state="visible", timeout=FAST_TIMEOUT)
        await locator.click()
        print("[llm_analyzer] Clicked direct Connect button.")
        return True

    elif strategy == "dropdown":
        element = analysis.get("element")
        if not element:
            return False
        locator = await get_element_locator(page, element)
        await locator.wait_for(state="visible", timeout=FAST_TIMEOUT)
        await _robust_click(page, locator)
        await asyncio.sleep(0.5)

        if await _click_connect_in_dropdown(page, vanity_name=vanity_name):
            print("[llm_analyzer] Clicked Connect inside dropdown.")
            return True

        await page.keyboard.press("Escape")
        return False

    return False


# ---------------------------------------------------------------------------
# Post-click: handle modal + detect success
# ---------------------------------------------------------------------------

async def _handle_post_click(
    page: Page,
    audit: "AuditLogger | None" = None,
) -> bool:
    await asyncio.sleep(0.8)

    # "Add a note?" modal
    for selector in MODAL_SEND_WITHOUT_NOTE:
        try:
            btn = page.locator(selector).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print("[post_click] Dismissed 'Add a note' modal.")
            if audit:
                audit.post_click("Dismissed 'Add a note' modal")
            break
        except PWTimeout:
            continue
    else:
        # "How do you know X?" modal — scope to [role="dialog"] so we don't
        # accidentally rematch the profile's Connect button still visible in <main>
        dialog = page.locator('[role="dialog"]')
        for selector in MODAL_CONNECT_BUTTON:
            try:
                btn = dialog.locator(selector).first
                await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
                await btn.click()
                print("[post_click] Clicked Connect inside modal.")
                if audit:
                    audit.post_click("Clicked Connect inside modal")
                break
            except PWTimeout:
                continue

    await asyncio.sleep(1.0)  # let toast/UI settle before reading state

    return await _detect_success(page, audit=audit)


async def _detect_success(page: Page, audit: "AuditLogger | None" = None) -> bool:
    # Step 1: check for error toast first — takes priority over everything
    for selector in ERROR_TOAST:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=2_000)
            text = await page.locator(selector).first.inner_text()
            print(f"[detect_success] Error toast detected: '{text.strip()}' — invite failed.")
            if audit:
                audit.success_detection(f"error toast: '{text.strip()}'", False)
            return False
        except PWTimeout:
            continue

    # Step 2: check for explicit success toast
    for selector in SUCCESS_TOAST:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=SLOW_TIMEOUT)
            print("[detect_success] Invitation sent toast detected.")
            if audit:
                audit.success_detection("success toast", True)
            return True
        except PWTimeout:
            continue

    # Step 3: Pending button appeared — most reliable signal after dropdown invite.
    # When Connect is sent via More dropdown, the direct connect link is never in
    # the page so button-gone can't work. Pending appearing IS the confirmation.
    main = page.locator("main")
    for selector in PENDING_SELECTORS:
        try:
            await main.locator(selector).first.wait_for(state="visible", timeout=SLOW_TIMEOUT)
            print(f"[detect_success] Pending button appeared ({selector}) — invite sent.")
            if audit:
                audit.success_detection(f"pending button appeared ({selector})", True)
            return True
        except PWTimeout:
            continue

    # Step 4: fallback — Connect button disappearing usually means success.
    # Only check selectors where the element is actually present on the page first —
    # an element that was never there is immediately "hidden", causing a false positive.
    for selector in [CONNECT_LINK_HREF, CONNECT_LINK_ARIA, CONNECT_BUTTON_ARIA, ADD_BUTTON_ARIA]:
        if await main.locator(selector).count() == 0:
            continue
        try:
            await main.locator(selector).first.wait_for(state="hidden", timeout=SLOW_TIMEOUT)
            for err_selector in ERROR_TOAST:
                try:
                    await page.locator(err_selector).first.wait_for(state="visible", timeout=1_000)
                    text = await page.locator(err_selector).first.inner_text()
                    print(f"[detect_success] Error toast after button gone: '{text.strip()}' — invite failed.")
                    if audit:
                        audit.success_detection(f"button gone + error toast: '{text.strip()}'", False)
                    return False
                except PWTimeout:
                    continue
            print(f"[detect_success] Button gone ({selector}) — invite sent.")
            if audit:
                audit.success_detection(f"button gone ({selector})", True)
            return True
        except PWTimeout:
            continue

    print("[detect_success] Could not confirm success.")
    if audit:
        audit.success_detection("none — could not confirm", False)
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _find_profile_header_section(page: Page):
    """
    Return a Locator scoped to the profile action strip section, or None.

    Uses the custom-invite link or More button as an anchor to find the
    containing <section> element. This lets broad text selectors be safely
    scoped so they can't match sidebar "People you may know" cards.
    """
    main = page.locator("main")
    for anchor_sel in [
        'a[href*="/preload/custom-invite/"]',
        'button[aria-label="More"][aria-expanded]',
        'button[aria-label="More actions"][aria-expanded]',
    ]:
        section = main.locator("section").filter(has=page.locator(anchor_sel))
        try:
            await section.first.wait_for(state="attached", timeout=FAST_TIMEOUT)
            return section.first
        except PWTimeout:
            continue
    return None


async def _check_profile_state(page: Page) -> str:
    """
    Return 'pending', 'connected', or 'unknown' based on visible action buttons.
    Scoped to <main> to avoid sidebar cards influencing the result.
    """
    main = page.locator("main")
    for selector in PENDING_SELECTORS:
        try:
            await main.locator(selector).first.wait_for(state="visible", timeout=2_000)
            return "pending"
        except PWTimeout:
            continue
    for selector in ALREADY_CONNECTED_SELECTORS:
        try:
            await main.locator(selector).first.wait_for(state="visible", timeout=2_000)
            # A "Message" button alone means connected. But some profiles show
            # "Message" (InMail) alongside a Connect/Add button — that means NOT
            # connected yet. Only call it connected if no Connect/Add button exists.
            has_connect_btn = await main.locator(
                'a[href*="/preload/custom-invite/"], '
                'button[aria-label*="Connect"], button[aria-label*="Add"], '
                'button[aria-label="More"]'
            ).count() > 0
            if has_connect_btn:
                return "unknown"
            return "connected"
        except PWTimeout:
            continue
    return "unknown"


def _extract_vanity_name(profile_url: str) -> str | None:
    """Extract the vanity name from a LinkedIn profile URL.
    e.g. https://www.linkedin.com/in/john-doe-123/ → 'john-doe-123'
    """
    from urllib.parse import urlparse
    path = urlparse(profile_url).path  # /in/john-doe-123/
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[0] == "in":
        return parts[1]
    return None


async def _wait_for_profile_load(page: Page) -> None:
    try:
        await page.locator("main").wait_for(state="visible", timeout=SLOW_TIMEOUT)
    except PWTimeout:
        pass
