"""
LinkedIn page analyzer — uses Ollama (llama3.1:8b) to identify which button
to click for sending a connection invite, regardless of A/B layout.

No vision needed — the DOM element list is descriptive enough.
"""

import json
import re
from playwright.async_api import Page
import ollama

OLLAMA_MODEL = "llama3.1:8b"

# Cast a wide net — grabs buttons, links, menu items across all layout variants
_ELEMENT_QUERY = """
() => {
    const selectors = 'button, a[role="button"], [role="menuitem"]';
    const els = Array.from(document.querySelectorAll(selectors));
    return els
        .map((el, i) => ({
            index: i,
            tag: el.tagName.toLowerCase(),
            text: (el.innerText || '').trim().replace(/\\s+/g, ' ').substring(0, 80),
            ariaLabel: el.getAttribute('aria-label') || '',
            dataControlName: el.getAttribute('data-control-name') || '',
            disabled: el.disabled || false,
            visible: el.offsetParent !== null,
        }))
        .filter(e => (e.text || e.ariaLabel) && !e.disabled && e.visible);
}
"""

_PROMPT_TEMPLATE = """\
You are analyzing a LinkedIn profile page. Below is a JSON list of all visible, enabled interactive elements (buttons and links) on the page.

Your job: identify which element to click to send a connection invite.

Rules:
- The button may say "Connect" or "Add" (both mean the same thing on LinkedIn).
- If Connect/Add is not directly visible, it may be hidden under a "More" or "..." dropdown button — in that case use strategy "dropdown" and give both the More button index AND the Connect/Add item index (once the dropdown is open, it will appear as a new element — pick the most likely index based on typical LinkedIn layouts, usually right after the More button).
- Do NOT pick "Follow", "Message", or "Unfollow".

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

OR if Connect is under a More/dropdown:
{{
  "strategy": "dropdown",
  "element_index": <index of More button>,
  "dropdown_connect_index": <expected index of Connect after dropdown opens>,
  "label": "More",
  "confidence": "medium",
  "notes": "<one line>"
}}

OR if nothing found:
{{
  "strategy": "none",
  "notes": "<reason>"
}}
"""


async def analyze_connect_button(page: Page) -> dict | None:
    """
    Extracts DOM elements and asks Ollama which one to click.
    Returns a dict with strategy + element indices, or None on failure.
    """
    elements: list[dict] = await page.evaluate(_ELEMENT_QUERY)

    if not elements:
        print("[analyzer] No interactive elements found on page.")
        return None

    print(f"[analyzer] Sending {len(elements)} elements to {OLLAMA_MODEL}...")

    prompt = _PROMPT_TEMPLATE.format(elements=json.dumps(elements, indent=2))

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},  # deterministic
    )

    raw = response["message"]["content"].strip()
    print(f"[analyzer] Ollama response: {raw}")

    result = _parse_json(raw)
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
    Build the most stable locator for an extracted element.
    Priority: aria-label > data-control-name > text content.
    """
    tag = element.get("tag", "button")
    aria = element.get("ariaLabel")
    control = element.get("dataControlName")
    text = element.get("text")

    if aria:
        return page.locator(f'{tag}[aria-label="{aria}"]').first
    if control:
        return page.locator(f'{tag}[data-control-name="{control}"]').first
    if text:
        return page.locator(f'{tag}:has-text("{text}")').first

    # Last resort: positional (fragile but functional)
    index = element.get("index", 0)
    return page.locator(tag).nth(index)
