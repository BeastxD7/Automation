"""
LinkedIn one-time login helper.

Opens a visible browser window pointed at LinkedIn's login page.
You log in manually (email + password + any 2FA).
Once the feed is detected the session is saved automatically to
.linkedin_session/ by Playwright's persistent context — no extra
steps needed. Future automation runs reuse that saved session.

Usage:
    python main.py login
"""

import asyncio
from playwright.async_api import TimeoutError as PWTimeout
from linkedin.send_invite import get_linkedin_context

LOGIN_URL = "https://www.linkedin.com/login"
FEED_INDICATORS = [
    'a[href*="/feed"]',
    'div[data-test-id="nav-feed-icon"]',
    '.global-nav__primary-link',
    'input[placeholder*="Search"]',
]


async def do_login() -> bool:
    """
    Open a browser, let the user log in manually, wait for the feed to load,
    then close. The session is persisted automatically in .linkedin_session/.
    """
    print("[login] Opening browser — please log in with your LinkedIn credentials.")
    print("[login] The window will close automatically once login is detected.\n")

    async with get_linkedin_context(headless=False) as (browser, page):
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=20_000)

        # Wait up to 3 minutes for the user to complete login (including 2FA etc.)
        for _ in range(180):
            await asyncio.sleep(1)
            current_url = page.url

            if "linkedin.com/feed" in current_url or "linkedin.com/in/" in current_url:
                print("[login] Feed detected — login successful! Session saved.")
                await asyncio.sleep(1)  # let any final XHR settle
                return True

            # Also check for feed elements (LinkedIn sometimes stays on /login URL briefly)
            for selector in FEED_INDICATORS:
                try:
                    el = page.locator(selector).first
                    await el.wait_for(state="visible", timeout=500)
                    print("[login] Feed element detected — login successful! Session saved.")
                    await asyncio.sleep(1)
                    return True
                except PWTimeout:
                    continue

        print("[login] Timed out waiting for login. Please try again.")
        return False
