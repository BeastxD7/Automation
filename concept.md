# LinkedIn Automation — How It Works (Simple English)

Think of this automation as a **robot assistant** that opens your LinkedIn, visits someone's profile, and clicks the Connect button for you — exactly like a human would, just faster and without getting bored.

---

## The Big Picture

```
You run the command
        │
        ▼
Robot opens Chrome browser (with your saved login)
        │
        ▼
Robot visits the profile URL you gave it
        │
        ▼
Robot checks: "Should I even bother trying?"
        │
        ▼
Robot tries to find and click the Connect/Add button
        │
        ▼
Robot handles any popup that appears after clicking
        │
        ▼
Robot checks: "Did the invite actually get sent?"
        │
        ▼
Tells you the result: sent / pending / connected / failed
```

---

## Part 1 — Login (One-Time Setup)

Before the robot can do anything, it needs to be logged into your LinkedIn account.

You run this once:
```
uv run python main.py login
```

A Chrome window opens. **You** log in manually (type email, password, do 2FA if needed). Once LinkedIn shows your feed, the robot saves your login session to a folder called `.linkedin_session/`. Think of this as saving your "logged-in cookies" so you never have to log in again.

Every future run reuses this saved session — the robot just picks up where you left off.

---

## Part 2 — Sending an Invite

You run:
```
uv run python main.py invite https://www.linkedin.com/in/john-doe/
```

Here is everything that happens, step by step.

---

### Step 1 — Open the Profile Page

The robot opens Chrome (using your saved session) and navigates to the profile URL. It waits for the main content of the page to load before doing anything.

---

### Step 2 — Handle the Signup Popup

LinkedIn sometimes shows a "Join LinkedIn!" popup over the profile even when you're logged in. The robot checks for this and dismisses it. If the page has fully redirected to a login wall, it stops immediately and tells you to log in again.

---

### Step 3 — Check the Profile State (Before Touching Anything)

Before trying to click anything, the robot looks at the page and asks three questions:

**"Is there a Pending button?"**
If yes → you already sent this person an invite before, it's waiting for their acceptance. Robot stops and returns `pending`.

**"Is there a Message button AND no Connect/Add button?"**
If yes → you're already connected with this person. Robot stops and returns `connected`.

> Why check Message button + no Connect button? Because LinkedIn shows a Message (InMail) button even on profiles you're NOT connected to — alongside the Add/Connect button. So Message alone doesn't mean connected. Only "Message with NO Add/Connect button" means truly connected.

**"Is there a weekly invite limit warning?"**
If yes → LinkedIn has blocked you from sending more invites this week. Robot stops and returns `limit_reached`.

**"Is there only a Follow button and no Connect/Add/More button at all?"**
If yes → this profile has disabled connection requests. Robot stops and returns `follow_only`.

If none of the above → the robot proceeds to find and click the button.

---

### Step 4 — Finding the Connect/Add Button (3 Strategies)

This is the most important part. LinkedIn's layout changes frequently (A/B tests, different account types), so the robot tries three strategies in order, from most precise to most flexible.

```
Strategy 1: Direct button on the page
        │
        ├── Found it? → Click it → Done ✓
        │
        └── Not found? ↓

Strategy 2: Hidden inside "More" dropdown
        │
        ├── Found it? → Click More → Click Connect inside → Done ✓
        │
        └── Not found? ↓

Strategy 3: Smart element analysis (LLM analyzer)
        │
        ├── Found it? → Click it → Done ✓
        │
        └── Not found? → Return "failed"
```

---

#### Strategy 1 — Direct Button

The robot looks for the Connect or Add button directly visible on the profile page, in this order:

**1a. Vanity name match (most precise)**
LinkedIn's Connect button often has a URL like:
```
href="/preload/custom-invite/?vanityName=john-doe"
```
The robot looks for an `<a>` tag whose href contains `vanityName=john-doe` (the exact person's name from the URL you gave it). This is the hardest guarantee — only the target person's button has their own vanity name in it. Sidebar "People You May Know" suggestions have *different* vanity names so they can never accidentally match.

**1b. Custom-invite link**
Looks for any `<a>` tag whose href contains `/preload/custom-invite/`. This is LinkedIn's standard URL pattern for all Connect buttons.

**1c. Aria-label match (scoped to the profile header section)**
Looks for `button[aria-label*="connect" i]` or `button[aria-label*="Add"]`. The `i` means case-insensitive, so it matches both `"Connect"` and `"Invite John to connect"`.

> Why scope to the profile header section? Because LinkedIn's right sidebar shows "People You May Know" with their own Connect buttons. If the robot searched the whole page, it might click the wrong person's button. By scoping to just the profile header section, only the target person's buttons are considered.

**Real example — what the Add button looks like in HTML:**
```html
<button aria-label="Invite John william to connect">
    <span>Add</span>
</button>
```
The button *text* says "Add" but the aria-label says "Invite John william to connect". The robot matches it via `aria-label*="connect" i`.

---

#### Strategy 2 — More Dropdown

Sometimes LinkedIn hides the Connect option inside a "More" overflow menu. You've probably seen this — a button labeled "More" with a dropdown that contains Connect, Follow, Report, etc.

```
Profile page:
┌─────────────────────────────────────────┐
│  [Message]  [Follow]  [More ▾]          │
└─────────────────────────────────────────┘
                              │
                              ▼ click More
┌─────────────────────────────────────────┐
│  ✓ Connect                              │
│    Send profile in a message            │
│    Save to PDF                          │
│    Follow                               │
│    Report / Block                       │
└─────────────────────────────────────────┘
```

The robot:
1. Looks for the More button (`button[aria-label="More actions"]` etc.)
2. Clicks it using a special "robust click" (explained below)
3. Waits for the dropdown to open
4. Looks for the Connect/Add option inside the dropdown, using the vanity name match first for safety
5. Clicks Connect

**Why "robust click"?**
LinkedIn sometimes has invisible overlays (cookie banners, notification bars) that block normal clicks. The robot first tries a regular click. If that fails because something is intercepting it, it falls back to a direct JavaScript click (`element.click()`) which bypasses any overlay.

**Where does the dropdown appear in the DOM?**
LinkedIn renders the open dropdown in a special browser layer called `popover="manual"` — it floats above everything else on the page. The robot looks for `div[role="menu"]` inside this layer to find the dropdown contents.

---

#### Strategy 3 — Smart Element Analysis (LLM Analyzer)

This is the fallback when neither Strategy 1 nor Strategy 2 found anything. It's used when LinkedIn has changed its layout so much that the hardcoded selectors no longer work.

**How it extracts elements:**

A JavaScript snippet runs inside the browser and collects interactive elements from the page. It works like this:

```
1. Find the connect link by vanityName in href → tag it "connect-link-targeted"
2. If not found, find any /preload/custom-invite/ link → tag it "connect-link"
3. Find the DOM section containing that link (or the More button as fallback)
4. Collect all buttons and menu items inside that section → tag them "profile-actions"
5. Remove: Follow, Unfollow, Message, mutual-connection links
6. Return the cleaned list with section tags
```

**How it decides what to click (deterministic logic, no AI needed in most cases):**

```
Has "connect-link-targeted" element?
    YES → strategy: direct, click it (HIGH confidence)

Has "connect-link" element?
    YES → strategy: direct, click it (HIGH confidence)

Has "profile-actions" element with "connect" or "add" in its text/aria-label?
    YES → strategy: direct, click it (MEDIUM confidence)

Has "profile-actions" element with "more" in its text/aria-label?
    YES → strategy: dropdown, click the More button (MEDIUM confidence)

None of the above?
    → Ask Ollama LLM (last resort — only when layout is truly unrecognizable)
```

The key insight: by the time elements are collected, they're already tagged with *why* they were included. The robot reads those tags instead of guessing. The LLM (Ollama) is only called when the tags aren't enough.

**Safety net:** Even if the LLM picks something, the robot checks it one more time — if it's a Follow, Message, or Unfollow button, it refuses to click it regardless of what the LLM said.

---

### Step 5 — Handling the Popup After Clicking

After clicking Connect/Add, LinkedIn often shows one of two modals:

**"Add a note?" modal:**
```
┌─────────────────────────────────────────┐
│  Add a note to your invitation?         │
│                                         │
│  [Add a note]   [Send without a note]   │
└─────────────────────────────────────────┘
```
Robot clicks "Send without a note".

**"How do you know X?" modal:**
```
┌─────────────────────────────────────────┐
│  How do you know John?                  │
│  ○ Colleague  ○ Classmate  ○ Friend...  │
│                                         │
│  [Connect]                              │
└─────────────────────────────────────────┘
```
Robot clicks "Connect" inside the modal (scoped to `[role="dialog"]` so it can't accidentally click the Connect button on the main page behind it).

---

### Step 6 — Did the Invite Actually Send?

After handling the modal, the robot checks whether the invite was successfully sent. It checks in this order:

```
1. Error toast appeared?
   e.g. "Unable to connect", "something went wrong"
   → Return FAILED

2. Success toast appeared?
   e.g. "Invitation sent"
   → Return SENT ✓

3. Pending button appeared?
   e.g. button[aria-label*="Pending"]
   This is the most reliable signal after a dropdown invite,
   because the Connect link was never directly on the page.
   → Return SENT ✓

4. Connect/Add button disappeared?
   If the button that was there before is now gone, and no
   error toast appeared, the invite was likely sent.
   → Return SENT ✓

5. None of the above?
   → Return FAILED (couldn't confirm)
```

---

## Part 3 — Result Statuses

| Status | What it means |
|---|---|
| `sent` | Invite sent successfully |
| `pending` | You already sent this person an invite before, still waiting |
| `connected` | You're already connected — nothing to do |
| `limit_reached` | LinkedIn blocked you — weekly invite limit hit |
| `follow_only` | This profile disabled connection requests entirely |
| `failed` | Something went wrong — auth wall, layout changed, all strategies failed |

---

## Part 4 — How the Robot Avoids Clicking the Wrong Person

This is a common concern: LinkedIn's sidebar shows suggested people with their own Connect buttons. The robot has multiple layers of protection:

**Layer 1 — Vanity name in href**
`a[href*="vanityName=john-doe"]` — only the target person's button has their vanity name in the URL. Sidebar suggestions have different names.

**Layer 2 — DOM section scoping**
The robot anchors to the DOM section containing the target's connect link, then only looks for buttons *inside that section*. Sidebar suggestions are in a completely different section.

**Layer 3 — Mutual connection link blocking**
LinkedIn shows "X mutual connections" as a link that contains the word "connection". The robot blocks any link whose href contains `/search/results/people/` so it can never accidentally navigate to a search page instead of clicking Connect.

**Layer 4 — Blocked element list**
Follow, Unfollow, and Message buttons are filtered out before any decision is made. Even if the LLM somehow picks one of these, there's a final safety check that refuses to click it.

---

## Part 5 — Audit Logs

Every single run creates a detailed log file in `logs/`. Example:
```
logs/2026-04-06_14-32-01_john-doe.log
```

The log records everything:
- Which profile was targeted
- What state the profile was in (pending/connected/unknown)
- Every selector tried and whether it hit or missed
- Which strategy succeeded
- What the LLM received and what it responded (if LLM was used)
- Which modal was dismissed (if any)
- How success was detected
- The final result

This is useful for debugging when the automation fails — you can see exactly where it got stuck.

---

## Summary Flow (The Full Picture)

```
uv run python main.py invite <url>
            │
            ▼
    Open Chrome with saved session
            │
            ▼
    Navigate to profile URL
            │
            ▼
    Dismiss signup popup (if any)
            │
            ▼
    ┌── Profile state check ──────────────────────────┐
    │  Pending button?       → return "pending"        │
    │  Message + no Add?     → return "connected"      │
    │  Invite limit warning? → return "limit_reached"  │
    │  Follow only?          → return "follow_only"    │
    └── None of above → continue ────────────────────-─┘
            │
            ▼
    ┌── Strategy 1: Direct button ──────────────────┐
    │  Try vanityName href match                     │
    │  Try /preload/custom-invite/ link              │
    │  Try aria-label connect/add match (in header)  │
    └── Hit? → Click → Go to Post-Click ────────────┘
            │ Miss?
            ▼
    ┌── Strategy 2: More dropdown ──────────────────┐
    │  Find More button                              │
    │  Click it (robust click)                       │
    │  Wait for dropdown to open                     │
    │  Find Connect inside dropdown (vanity first)   │
    └── Hit? → Click → Go to Post-Click ────────────┘
            │ Miss?
            ▼
    ┌── Strategy 3: LLM Analyzer ───────────────────┐
    │  Run JS to collect tagged elements             │
    │  Deterministic decision from section tags      │
    │  (LLM only if deterministic fails)             │
    └── Hit? → Click → Go to Post-Click ────────────┘
            │ Miss?
            ▼
        return "failed"

    ── Post-Click ───────────────────────────────────
            │
            ▼
    Dismiss "Add a note?" or "How do you know X?" modal
            │
            ▼
    ┌── Success detection ──────────────────────────┐
    │  Error toast?          → return "failed"       │
    │  Success toast?        → return "sent"         │
    │  Pending button?       → return "sent"         │
    │  Connect button gone?  → return "sent"         │
    │  None?                 → return "failed"       │
    └────────────────────────────────────────────────┘
```
