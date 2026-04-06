# Automations

LinkedIn connection invite automation using Playwright.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast Python package manager
- [Ollama](https://ollama.com) — local LLM (used as last-resort fallback for finding the Connect button)

## Setup

**1. Clone the repo**

```bash
git clone https://github.com/BeastxD7/Automation.git
cd automations
```

**2. Install dependencies**

```bash
uv sync
```

**3. Install Playwright browsers**

```bash
uv run playwright install chromium
```

**4. Pull the Ollama model** *(only needed if hardcoded selectors fail)*

```bash
ollama pull llama3.1:8b
```

## Usage

### Step 1 — Login (one-time only)

Opens a browser window. Log in with your LinkedIn email and password (including any 2FA). The window closes automatically once login is detected and the session is saved locally.

```bash
uv run python main.py login
```

> The session is saved to `.linkedin_session/` and reused automatically on all future runs.

### Step 2 — Send a connection invite

```bash
uv run python main.py invite https://www.linkedin.com/in/some-person/
```

### Force LLM mode (skip hardcoded selectors)

Skips strategies 1 and 2 and goes straight to the Ollama LLM analyzer. Useful for testing the LLM path or when LinkedIn's layout has changed and selectors are broken.

```bash
uv run python main.py invite https://www.linkedin.com/in/some-person/ --force-llm
```

### Result statuses

| Status | Meaning |
|---|---|
| `sent` | Invite successfully sent |
| `pending` | Invite already sent previously, waiting for acceptance |
| `connected` | Already connected, nothing to do |
| `limit_reached` | LinkedIn weekly invitation limit hit |
| `follow_only` | Profile only allows Follow — no Connect option exists |
| `failed` | Auth wall, selectors broke, or all strategies exhausted |

## How it works

Before attempting any strategy, the automation checks if an invite is already **pending** or the profiles are already **connected** — and skips immediately if so.

The automation then tries three strategies in order to find and click the Connect button:

1. **Direct selector** — matches the Connect link by exact `vanityName` query param in the href (e.g. `a[href*="vanityName=john-doe"]`), scoped to `<main>` only. This is the hard guarantee that only the target lead's button is clicked — sidebar suggestions have different vanity names so they can never match.
2. **More dropdown** — if Connect is hidden behind a "More" overflow menu
3. **LLM analyzer** *(fallback)* — collects interactive elements from the profile action strip (DOM-scoped, not pixel-based) and asks Ollama which one to click. Elements are pre-filtered to the section containing the target's connect link before being sent to the LLM.

After clicking, the automation handles any modal ("Add a note?" / "How do you know X?") and then verifies the result via success/error toasts or the Connect button disappearing.

## Audit logs

Every invite attempt writes a detailed audit log to `logs/` named `YYYY-MM-DD_HH-MM-SS_<vanity-name>.log`.

Each log captures the full lifecycle of the attempt:

- **Target** — profile URL and vanity name
- **Profile state check** — pending / connected / unknown before any action
- **Strategy attempts** — every CSS selector tried with HIT/MISS for each
- **LLM input** — the exact list of DOM elements sent to Ollama
- **LLM prompt** — the final rendered prompt (template variables replaced with actual values)
- **LLM output** — raw response from Ollama and the parsed JSON result
- **Post-click actions** — which modal was dismissed (if any)
- **Success detection** — method used and outcome (error toast / success toast / button gone)
- **Final result** — `SENT`, `PENDING`, `CONNECTED`, or `FAILED`

Example log location:
```
logs/2026-04-06_14-32-01_royalsalins.log
```

> Logs are gitignored — they stay local and are never committed.

## File structure

```
automations/
├── main.py                  # Entry point (login / invite commands)
├── linkedin/
│   ├── login.py             # One-time manual login flow
│   ├── send_invite.py       # Core invite logic + strategy orchestration
│   ├── selectors.py         # CSS selectors (update here when LinkedIn changes layout)
│   ├── analyzer.py          # Ollama LLM fallback (element collection + prompting)
│   └── audit.py             # Audit logger — writes per-run log files
├── logs/                    # Audit logs (gitignored)
└── .linkedin_session/       # Saved browser session — never commit this
```

## Updating selectors

LinkedIn frequently A/B tests its UI. If the automation stops finding the Connect button, inspect the button in DevTools, then update `linkedin/selectors.py`.
