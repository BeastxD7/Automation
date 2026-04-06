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

## How it works

The automation tries three strategies in order to find and click the Connect button:

1. **Direct selector** — matches the Connect link/button scoped to `<main>` using the target profile's vanity name (avoids clicking sidebar suggestions)
2. **More dropdown** — if Connect is hidden behind a "More" overflow menu
3. **LLM analyzer** *(fallback)* — takes a screenshot and asks Ollama to locate the button when LinkedIn's A/B tested layout breaks hardcoded selectors

## File structure

```
automations/
├── main.py                  # Entry point (login / invite commands)
├── linkedin/
│   ├── login.py             # One-time manual login flow
│   ├── send_invite.py       # Core invite logic
│   ├── selectors.py         # CSS selectors (update here when LinkedIn changes layout)
│   └── analyzer.py          # Ollama LLM fallback
└── .linkedin_session/       # Saved browser session — never commit this
```

## Updating selectors

LinkedIn frequently A/B tests its UI. If the automation stops finding the Connect button, inspect the button in DevTools, then update `linkedin/selectors.py`.
