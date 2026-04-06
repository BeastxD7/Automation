"""
LinkedIn page analyzer — uses Ollama (llama3.1:8b) to identify which button
to click for sending a connection invite, regardless of A/B layout.

No vision needed — the DOM element list is descriptive enough.
"""

import json
import re
from playwright.async_api import Page
import ollama
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from linkedin.audit import AuditLogger

OLLAMA_MODEL = "llama3.1:8b"

# Strategy:
# 1. Explicitly grab the custom-invite link (the actual Connect button as of 2026-04)
# 2. From the profile header zone (top 500px of <main>) grab all buttons/links
# 3. Deduplicate, tag each element with its Y position and section label
# This keeps the list small and scoped — "People also viewed" and activity
# sections are further down the page and won't appear.

# vanityName is injected at runtime via page.evaluate(fn, vanity_name)
_ELEMENT_QUERY = """
(vanityName) => {
    const seen = new Set();
    const results = [];

    function capture(el, sectionLabel) {
        if (seen.has(el)) return;
        seen.add(el);
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').substring(0, 100);
        const ariaLabel = el.getAttribute('aria-label') || '';
        if (!text && !ariaLabel) return;
        if (el.disabled) return;
        results.push({
            index: results.length,
            tag: el.tagName.toLowerCase(),
            text,
            ariaLabel,
            href: el.getAttribute('href') || '',
            section: sectionLabel,
        });
    }

    // Priority 1: connect link whose vanityName param matches the target exactly.
    // This is the hard guarantee — only the target lead's Connect button has this href.
    const targeted = vanityName
        ? Array.from(document.querySelectorAll(`a[href*="vanityName=${vanityName}"]`))
        : [];
    targeted.forEach(el => capture(el, 'connect-link-targeted'));

    // Priority 2: generic custom-invite fallback — runs when vanityName is absent
    // OR when the targeted query found nothing (e.g. href format differs for this profile).
    if (targeted.length === 0) {
        document.querySelectorAll('a[href*="/preload/custom-invite/"]')
            .forEach(el => capture(el, 'connect-link'));
    }

    // Priority 3: find the profile action strip section and collect its buttons.
    //
    // Anchor priority (most → least specific):
    //   a) Targeted connect link (vanityName match) — guaranteed to be in the right section
    //   b) Any custom-invite link — still in the profile strip
    //   c) The More button (aria-expanded attr marks it as a dropdown trigger) —
    //      used when Connect is hidden inside the dropdown, so no connect link exists
    //   d) Nothing found → return early, do NOT fall back to 'main section'
    //      because that risks grabbing sidebar "People you may know" elements
    //
    const connectLink = targeted[0]
        || document.querySelector('a[href*="/preload/custom-invite/"]');

    const moreButton = document.querySelector(
        'button[aria-label="More"][aria-expanded],' +
        'button[aria-label="More actions"][aria-expanded]'
    );

    const anchor = connectLink || moreButton;

    if (!anchor) {
        // No reliable anchor — bail out rather than risk the wrong section
        return results;
    }

    const headerSection = anchor.closest('section')
        || anchor.closest('[data-view-name]')
        || anchor.parentElement;

    if (headerSection) {
        headerSection.querySelectorAll('button, [role="menuitem"]')
            .forEach(el => capture(el, 'profile-actions'));
    }

    return results;
}
"""

_PROMPT_TEMPLATE = """\
You are analyzing a LinkedIn profile page for the person with vanity name "{vanity_name}".
Below is a JSON list of interactive elements from the profile action strip (Follow/Message/Unfollow have already been removed).

Your job: identify which element to click to send a connection invite TO "{vanity_name}".

Decision rules — follow them in order:
1. If any element has text or aria-label containing "Connect" or "Add" → strategy "direct", pick that element.
2. If no Connect/Add is visible BUT a "More" or "..." button is present → strategy "dropdown". Connect is hidden inside the dropdown. Pick the More button as element_index. For dropdown_connect_index, use the index right after the More button (Connect almost always appears first in the dropdown).
3. If neither Connect/Add nor More/... is present → strategy "none".

IMPORTANT: Never pick Follow, Message, or Unfollow — those have already been filtered but if any slip through, ignore them.

Elements:
{elements}

Respond with ONLY a raw JSON object. No markdown fences, no explanation, just JSON:
{{
  "strategy": "direct",
  "element_index": <number>,
  "label": "<button text or aria-label>",
  "confidence": "high",
  "notes": "<one line>"
}}

OR:
{{
  "strategy": "dropdown",
  "element_index": <index of More button>,
  "dropdown_connect_index": <expected index of Connect once dropdown opens>,
  "label": "More",
  "confidence": "medium",
  "notes": "<one line>"
}}

OR:
{{
  "strategy": "none",
  "notes": "<reason>"
}}
"""

# Text/aria-label patterns that must never be clicked regardless of LLM output
_BLOCKED_LABELS = {"follow", "unfollow", "following", "message", "message rahul"}
_BLOCKED_PATTERNS = ["follow", "unfollow", "message"]


def _is_blocked(element: dict) -> bool:
    """Return True if this element should never be clicked (wrong action type)."""
    text = (element.get("text") or "").lower().strip()
    aria = (element.get("ariaLabel") or "").lower().strip()
    href = (element.get("href") or "").lower()

    for pattern in _BLOCKED_PATTERNS:
        if pattern in text or pattern in aria:
            return True

    # Mutual connection search links — clicking these navigates away from the profile
    if "/search/results/people/" in href:
        return True

    return False


async def analyze_connect_button(
    page: Page,
    vanity_name: str | None = None,
    audit: "AuditLogger | None" = None,
) -> dict | None:
    """
    Extracts DOM elements from <main> and asks Ollama which one to click.
    Returns a dict with strategy + element indices, or None on failure.
    """
    elements: list[dict] = await page.evaluate(_ELEMENT_QUERY, vanity_name)

    if not elements:
        print("[analyzer] No interactive elements found on page.")
        return None

    # Strip Follow/Message/Unfollow before the LLM ever sees them
    blocked = [e for e in elements if _is_blocked(e)]
    elements = [e for e in elements if not _is_blocked(e)]
    # Re-index after filtering so LLM indices are contiguous
    for i, el in enumerate(elements):
        el["index"] = i

    if blocked:
        print(f"[analyzer] Filtered out {len(blocked)} blocked element(s): "
              f"{[e.get('text') or e.get('ariaLabel') for e in blocked]}")

    if not elements:
        print("[analyzer] No actionable elements remain after filtering.")
        return None

    targeted = [e for e in elements if e.get("section") == "connect-link-targeted"]
    print(f"[analyzer] {len(elements)} elements collected "
          f"({len(targeted)} targeted connect link{'s' if len(targeted) != 1 else ''}) "
          f"— sending to {OLLAMA_MODEL}...")

    prompt = _PROMPT_TEMPLATE.format(
        vanity_name=vanity_name or "unknown",
        elements=json.dumps(elements, indent=2),
    )

    if audit:
        audit.llm_elements(elements)
        audit.llm_prompt(prompt)

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},  # deterministic
    )

    raw = response["message"]["content"].strip()
    print(f"[analyzer] Ollama response: {raw}")

    result = _parse_json(raw)
    if audit:
        audit.llm_response_raw(raw)
        audit.llm_response_parsed(result)

    if result is None:
        print("[analyzer] Failed to parse Ollama response as JSON.")
        return None

    if result.get("strategy") == "none":
        print(f"[analyzer] No connect button found — {result.get('notes')}")
        return None

    # Attach the actual element data so caller can build a stable locator
    idx = result.get("element_index")
    if idx is not None and 0 <= idx < len(elements):
        result["element"] = elements[idx]
    elif idx is not None:
        print(f"[analyzer] element_index {idx} out of range (only {len(elements)} elements) — LLM hallucinated.")
        return None

    dropdown_idx = result.get("dropdown_connect_index")
    if dropdown_idx is not None and 0 <= dropdown_idx < len(elements):
        result["dropdown_element"] = elements[dropdown_idx]
    # dropdown index being out of range is ok — caller falls back to selector scan

    return result


_POST_CLICK_QUERY = """
(vanityName) => {
    const results = [];
    const seen = new Set();

    function capture(el, section) {
        if (seen.has(el)) return;
        seen.add(el);
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return;
        const text = (el.innerText || '').trim().replace(/\\s+/g, ' ').substring(0, 120);
        const ariaLabel = el.getAttribute('aria-label') || '';
        if (!text && !ariaLabel) return;
        results.push({ tag: el.tagName.toLowerCase(), text, ariaLabel, href: el.getAttribute('href') || '', section });
    }

    // Toast / alert regions anywhere on page — carry the success/error message
    document.querySelectorAll('.artdeco-toast-item, [role="alert"], [aria-live="assertive"]')
        .forEach(el => capture(el, 'toast'));

    // Anchor priority for post-click (Connect link is gone after invite sent):
    //   a) vanityName connect link (still present if invite failed)
    //   b) Pending button containing vanityName (present after successful invite)
    //   c) More button with aria-expanded (always in the profile action strip)
    //   d) Nothing → skip, don't fall back to 'main section' to avoid sidebar
    const anchor = (vanityName && document.querySelector(`a[href*="vanityName=${vanityName}"]`))
        || (vanityName && document.querySelector(`button[aria-label*="${vanityName}"]`))
        || document.querySelector('button[aria-label*="Pending"]')
        || document.querySelector(
            'button[aria-label="More"][aria-expanded],' +
            'button[aria-label="More actions"][aria-expanded]'
        );

    if (!anchor) return results;  // only toasts returned — safer than grabbing wrong section

    const headerSection = anchor.closest('section')
        || anchor.closest('[data-view-name]')
        || anchor.parentElement;

    if (headerSection) {
        headerSection.querySelectorAll('button, a[href], [role="menuitem"]')
            .forEach(el => capture(el, 'profile-actions'));
    }

    return results;
}
"""

_POST_CLICK_PROMPT = """\
A LinkedIn connection invite was just clicked for the profile "{vanity_name}".
Below are the visible elements on the page right now (scoped to the main section + any toast/alert regions).

Determine whether the invite was successfully sent.

Signals that mean SUCCESS:
- A "Pending" button is visible (means invite is awaiting acceptance)
- A toast/alert containing "Invitation sent", "sent", or similar
- The Connect button is gone and no error is shown

Signals that mean FAILURE:
- A toast/alert containing "Unable to connect", "something went wrong", "can't be sent", "limit", "error"
- The Connect button is still present
- A "Withdraw" button appeared (invite was sent but immediately withdrawn — treat as failed)

Elements:
{elements}

Respond with ONLY a raw JSON object:
{{
  "result": "sent" or "failed",
  "confidence": "high" or "medium" or "low",
  "reason": "<one line explaining what you saw>"
}}
"""


async def analyze_invite_result(
    page: Page,
    vanity_name: str | None = None,
    audit: "AuditLogger | None" = None,
) -> dict | None:
    """
    After clicking Connect, ask Ollama to inspect the page and decide if the
    invite was successfully sent.
    Returns dict with keys: result ("sent"/"failed"), confidence, reason.
    """
    all_elements: list[dict] = await page.evaluate(_POST_CLICK_QUERY, vanity_name)

    if not all_elements:
        print("[analyzer] No elements found for post-click analysis.")
        return None

    print(f"[analyzer] Post-click: sending {len(all_elements)} elements to {OLLAMA_MODEL} (toasts + header zone)...")

    prompt = _POST_CLICK_PROMPT.format(
        vanity_name=vanity_name or "unknown",
        elements=json.dumps(all_elements, indent=2),
    )

    if audit:
        audit.llm_elements(all_elements)
        audit.llm_prompt(prompt)

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )

    raw = response["message"]["content"].strip()
    print(f"[analyzer] Post-click response: {raw}")

    result = _parse_json(raw)
    if audit:
        audit.llm_response_raw(raw)
        audit.llm_response_parsed(result)
    return result


def _parse_json(text: str) -> dict | None:
    """
    Robustly extract a JSON object from LLM output.
    Handles cases where the model wraps the JSON in markdown fences or adds prose.
    """
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    stripped = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Extract first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


async def get_element_locator(page: Page, element: dict):
    """
    Build the most stable locator for an extracted element, scoped to <main>.
    Priority: href (most specific) > aria-label > data-control-name > text content.
    """
    main = page.locator("main")
    tag = element.get("tag", "button")
    href = element.get("href")
    aria = element.get("ariaLabel")
    control = element.get("dataControlName")
    text = element.get("text")

    if href:
        return main.locator(f'{tag}[href="{href}"]').first
    if aria:
        return main.locator(f'{tag}[aria-label="{aria}"]').first
    if control:
        return main.locator(f'{tag}[data-control-name="{control}"]').first
    if text:
        return main.locator(f'{tag}:has-text("{text}")').first

    # Last resort: positional within main (fragile but functional)
    index = element.get("index", 0)
    return main.locator(tag).nth(index)
