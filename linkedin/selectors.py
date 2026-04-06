# LinkedIn selectors — isolated here because LinkedIn's A/B testing
# means these can change at any time. Update this file when layouts break.

# --- Connect / Add button (direct, visible in action strip) ---
# LinkedIn shows "Connect" or "Add" depending on layout/A/B test.
# As of 2026-04, the Connect button is an <a> tag (not <button>):
#   aria-label="Invite ... to connect", href="/preload/custom-invite/..."
CONNECT_BUTTON_ARIA = 'button[aria-label*="Connect"]'
CONNECT_BUTTON_TEXT = 'button:has-text("Connect")'
ADD_BUTTON_ARIA = 'button[aria-label*="Add"]'
ADD_BUTTON_TEXT = 'button:has-text("Add")'
# <a>-tag variants (current LinkedIn layout)
CONNECT_LINK_ARIA = 'a[aria-label*="connect"]'
CONNECT_LINK_HREF = 'a[href*="/preload/custom-invite/"]'
CONNECT_LINK_TEXT = 'a:has-text("Connect")'

# --- "More" overflow dropdown (hides Connect in some layouts) ---
# Layout B/C: Connect is buried under a "More" or "..." button
MORE_BUTTON_SELECTORS = [
    'button[aria-label="More actions"]',
    'button:has-text("More")',
    'button[aria-label*="More"]',
    # icon-only variant (three dots)
    'button.artdeco-dropdown__trigger',
]

# Connect / Add option inside the dropdown
CONNECT_IN_DROPDOWN = [
    'div[aria-label*="Connect"]',
    'div[aria-label*="Add"]',
    'span:has-text("Connect")',
    'span:has-text("Add")',
    'li:has-text("Connect") button',
    'li:has-text("Add") button',
]

# --- Modal (shown after clicking Connect) ---
# "How do you know X?" / "Add a note?" modal
MODAL_SEND_WITHOUT_NOTE = [
    'button[aria-label="Send without a note"]',
    'button:has-text("Send without a note")',
    'button:has-text("Send now")',
]
MODAL_CONNECT_BUTTON = [
    'button[aria-label*="Connect"]',
    'button:has-text("Connect")',
]

# --- Signup / login wall (shown to logged-out users or on bot detection) ---
SIGNUP_MODAL_CLOSE = [
    'button[aria-label="Dismiss"]',
    'button[aria-label="Close"]',
    'button.modal__dismiss',
    'button[data-tracking-control-name="public_profile_join-now-top-bar_dismiss"]',
]
# If the whole page redirected to signup/login, we can detect it by URL or heading
SIGNUP_PAGE_INDICATORS = [
    'a:has-text("Sign in")',
    'h1:has-text("Join LinkedIn")',
    'h1:has-text("Log In")',
]

# Success indicators — toast or confirmation
SUCCESS_TOAST = [
    'div[aria-label*="Invitation sent"]',
    'span:has-text("Invitation sent")',
    '.artdeco-toast-item',
]
