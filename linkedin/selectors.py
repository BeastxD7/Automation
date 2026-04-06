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
# As of 2026-04: <button aria-label="More" aria-expanded="false">
MORE_BUTTON_SELECTORS = [
    'button[aria-label="More"]',           # exact match — current layout
    'button[aria-label="More actions"]',   # alternate aria-label seen in some A/B tests
    'button[aria-label*="More"][aria-expanded]',  # any More button that is a dropdown trigger
    'button:has-text("More")',
    'button.artdeco-dropdown__trigger',
]

# Container that LinkedIn renders for an open dropdown menu
# Search for Connect INSIDE this container to avoid matching sidebar elements
DROPDOWN_CONTAINER_SELECTORS = [
    '.artdeco-dropdown__content',
    '[role="menu"]',
    '[role="listbox"]',
    # fallback: any visible list that appeared after clicking More
    'ul[class*="dropdown"]',
]

# Connect / Add option — used relative to the dropdown container, not the whole page
CONNECT_IN_DROPDOWN = [
    'div[aria-label*="Connect"]',
    'div[aria-label*="Add"]',
    'li:has-text("Connect") button',
    'li:has-text("Add") button',
    # These two are broad — only used as last resort inside the scoped container
    'span:has-text("Connect")',
    'span:has-text("Add")',
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

# --- Already-sent / already-connected states ---
# Shown when an invite is pending or the profiles are already connected
PENDING_SELECTORS = [
    'button[aria-label*="Pending"]',
    'button:has-text("Pending")',
    'a[aria-label*="Pending"]',
    'a:has-text("Pending")',
]
ALREADY_CONNECTED_SELECTORS = [
    'button[aria-label*="Message"]',   # "Message" replaces Connect once connected
    'a[aria-label*="Message"]',
    'button:has-text("Message")',
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
]

# Error/failure toast indicators
ERROR_TOAST = [
    'span:has-text("Unable to connect")',
    'span:has-text("something went wrong")',
    'span:has-text("can\'t be sent")',
    'span:has-text("couldn\'t send")',
    'div[aria-label*="error" i]',
    'div[aria-label*="failed" i]',
    # Generic artdeco error toast (has a distinct class from success)
    '.artdeco-toast-item--error',
]
