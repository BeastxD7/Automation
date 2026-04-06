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
    CONNECT_BUTTON_TEXT,
    ADD_BUTTON_ARIA,
    ADD_BUTTON_TEXT,
    CONNECT_LINK_ARIA,
    CONNECT_LINK_HREF,
    CONNECT_LINK_TEXT,
    MORE_BUTTON_SELECTORS,
    CONNECT_IN_DROPDOWN,
    MODAL_SEND_WITHOUT_NOTE,
    MODAL_CONNECT_BUTTON,
    SUCCESS_TOAST,
    SIGNUP_MODAL_CLOSE,
    SIGNUP_PAGE_INDICATORS,
)
from linkedin.analyzer import analyze_connect_button, get_element_locator

SESSION_DIR = Path(__file__).parent.parent / ".linkedin_session"
FAST_TIMEOUT = 3_000
SLOW_TIMEOUT = 8_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_invite(page: Page, profile_url: str) -> bool:
    """
    Navigate to a LinkedIn profile and send a connection invite.
    Returns True if the invite was sent, False otherwise.
    """
    try:
        await page.goto(profile_url, wait_until="domcontentloaded", timeout=20_000)
        await _wait_for_profile_load(page)
    except Exception as e:
        print(f"[send_invite] Navigation failed: {e}")
        return False

    # Must handle popup before anything else — it blocks all interactions
    if not await _handle_auth_wall(page):
        return False

    vanity_name = _extract_vanity_name(profile_url)

    # Strategy 1: direct Connect button
    try:
        if await _strategy_direct_connect(page, vanity_name):
            return await _handle_post_click(page)
    except Exception as e:
        print(f"[send_invite] direct_connect raised: {e}")

    # Strategy 2: More dropdown
    try:
        if await _strategy_more_dropdown(page):
            return await _handle_post_click(page)
    except Exception as e:
        print(f"[send_invite] more_dropdown raised: {e}")

    # Strategy 3: LLM analyzer (last resort)
    print("[send_invite] Hardcoded selectors failed — falling back to LLM analyzer.")
    try:
        if await _strategy_llm_analyzer(page):
            return await _handle_post_click(page)
    except Exception as e:
        print(f"[send_invite] llm_analyzer raised: {e}")

    print("[send_invite] All strategies exhausted.")
    return False


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

async def _strategy_direct_connect(page: Page, vanity_name: str | None = None) -> bool:
    # Scope every search to <main> to avoid sidebar "People you may know" Connect buttons.
    main = page.locator("main")

    # Most precise: link whose vanityName param matches the target profile exactly.
    if vanity_name:
        targeted = f'a[href*="vanityName={vanity_name}"]'
        try:
            btn = main.locator(targeted).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print(f"[direct_connect] Clicked via vanity-name href ({vanity_name})")
            return True
        except PWTimeout:
            pass

    # Broader fallbacks — still scoped to <main>
    for selector in [
        CONNECT_LINK_HREF,       # <a href="/preload/custom-invite/...">
        CONNECT_LINK_ARIA,       # <a aria-label="Invite ... to connect">
        CONNECT_LINK_TEXT,       # <a>Connect</a>
        CONNECT_BUTTON_ARIA,     # legacy <button aria-label*="Connect">
        CONNECT_BUTTON_TEXT,     # legacy <button>Connect</button>
        ADD_BUTTON_ARIA,
        ADD_BUTTON_TEXT,
    ]:
        try:
            btn = main.locator(selector).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print(f"[direct_connect] Clicked via: {selector}")
            return True
        except PWTimeout:
            continue
    return False


# ---------------------------------------------------------------------------
# Strategy 2: More dropdown → Connect
# ---------------------------------------------------------------------------

async def _strategy_more_dropdown(page: Page) -> bool:
    more_btn = None
    for selector in MORE_BUTTON_SELECTORS:
        try:
            candidate = page.locator(selector).first
            await candidate.wait_for(state="visible", timeout=FAST_TIMEOUT)
            more_btn = candidate
            break
        except PWTimeout:
            continue

    if more_btn is None:
        return False

    await more_btn.click()
    await asyncio.sleep(0.5)

    for selector in CONNECT_IN_DROPDOWN:
        try:
            option = page.locator(selector).first
            await option.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await option.click()
            print(f"[more_dropdown] Clicked Connect via: {selector}")
            return True
        except PWTimeout:
            continue

    await page.keyboard.press("Escape")
    return False


# ---------------------------------------------------------------------------
# Strategy 3: LLM analyzer (Ollama)
# ---------------------------------------------------------------------------

async def _strategy_llm_analyzer(page: Page) -> bool:
    analysis = await analyze_connect_button(page)
    if not analysis:
        return False

    strategy = analysis.get("strategy")
    print(f"[llm_analyzer] strategy={strategy}, confidence={analysis.get('confidence')}, label='{analysis.get('label')}', notes='{analysis.get('notes')}'")

    if strategy == "direct":
        element = analysis.get("element")
        if not element:
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
        await locator.click()
        await asyncio.sleep(0.5)

        # Try the LLM-identified dropdown item first
        dropdown_el = analysis.get("dropdown_element")
        if dropdown_el:
            try:
                connect_locator = await get_element_locator(page, dropdown_el)
                await connect_locator.wait_for(state="visible", timeout=FAST_TIMEOUT)
                await connect_locator.click()
                print("[llm_analyzer] Clicked Connect inside dropdown.")
                return True
            except PWTimeout:
                pass

        # Fallback: scan dropdown for Connect text
        for selector in CONNECT_IN_DROPDOWN:
            try:
                opt = page.locator(selector).first
                await opt.wait_for(state="visible", timeout=FAST_TIMEOUT)
                await opt.click()
                return True
            except PWTimeout:
                continue

        await page.keyboard.press("Escape")
        return False

    return False


# ---------------------------------------------------------------------------
# Post-click: handle modal + detect success
# ---------------------------------------------------------------------------

async def _handle_post_click(page: Page) -> bool:
    await asyncio.sleep(0.8)

    # "Add a note?" modal
    for selector in MODAL_SEND_WITHOUT_NOTE:
        try:
            btn = page.locator(selector).first
            await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
            await btn.click()
            print("[post_click] Dismissed 'Add a note' modal.")
            break
        except PWTimeout:
            continue
    else:
        # "How do you know X?" modal
        for selector in MODAL_CONNECT_BUTTON:
            try:
                btn = page.locator(selector).first
                await btn.wait_for(state="visible", timeout=FAST_TIMEOUT)
                await btn.click()
                print("[post_click] Clicked Connect inside modal.")
                break
            except PWTimeout:
                continue

    return await _detect_success(page)


async def _detect_success(page: Page) -> bool:
    for selector in SUCCESS_TOAST:
        try:
            toast = page.locator(selector).first
            await toast.wait_for(state="visible", timeout=SLOW_TIMEOUT)
            print("[detect_success] Invitation sent toast detected.")
            return True
        except PWTimeout:
            continue

    # Fallback: element disappearing = invite sent (works for button and link variants)
    for selector in [CONNECT_LINK_HREF, CONNECT_LINK_ARIA, CONNECT_BUTTON_ARIA, ADD_BUTTON_ARIA]:
        try:
            await page.locator(selector).wait_for(state="hidden", timeout=SLOW_TIMEOUT)
            print(f"[detect_success] Button gone ({selector}) — assuming success.")
            return True
        except PWTimeout:
            continue

    print("[detect_success] Could not confirm success.")
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
