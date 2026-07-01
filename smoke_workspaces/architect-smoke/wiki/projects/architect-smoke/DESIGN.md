# DESIGN — architect-smoke

## Tier Assessment

**Verdict:** agree  **Current tier:** Standard  **Recommended tier:** Standard

The project is a single local script, but credential management (Keychain or restricted .env), structured log persistence, a scheduler integration (cron or launchd), and a meaningful anti-automation surface from Craigslist's bot detection all clear the Micro bar. There is no multi-service architecture, no PII exposure beyond stored login credentials, and no external API, so Full is not warranted.

## Tech-Stack Options

### Python 3.11 + Playwright (vanilla, as PRD-specified)

**Pros:**
- Exactly what the PRD specifies; Python 3.11 and Playwright are already installed — zero additional runtime setup
- Async API and built-in smart-wait strategies handle dynamic DOM reliably without explicit sleep calls
- Rich selector engine (get_by_text, get_by_role, get_by_label) survives minor Craigslist HTML refactors better than raw CSS class selectors
- Official Playwright dialog event listener handles native browser window.confirm() automatically with one line
- Playwright's --headless flag and persistent browser context support are first-class features, not workarounds
**Cons:**
- Playwright's bundled Chromium exposes navigator.webdriver and CDP signals by default; Craigslist's bot detection could fingerprint and CAPTCHA the session over time
- No built-in stealth patching — the automation surface is wider than a real Chrome session
**Best if:** Craigslist does not aggressively fingerprint this specific personal-account renewal flow, and the operator accepts occasional CAPTCHA interruptions as a tolerable cost of the simplest possible stack.

### Python 3.11 + Playwright + playwright-stealth

**Pros:**
- Stays within the already-installed Playwright ecosystem while patching the most common automation fingerprints: navigator.webdriver, Chrome runtime object, plugins list, language headers
- Reduces CAPTCHA trigger probability without introducing a new browser binary or diverging from the PRD stack
- One additional pip dependency (playwright-stealth); no other setup change
**Cons:**
- playwright-stealth is a community library with intermittent maintenance — it can lag behind Playwright version increments and break silently on upgrade
- Stealth patches are not exhaustive; Craigslist could still fingerprint via canvas entropy, font metrics, or TLS fingerprint differences between Playwright Chromium and real Chrome
- Adds a dependency that must be audited for security and kept pinned
**Best if:** The operator wants a low-friction anti-fingerprint layer on top of Playwright to reduce CAPTCHA frequency, without switching to a different browser driver or binary.

### Python 3.11 + Selenium + undetected-chromedriver

**Pros:**
- undetected-chromedriver is purpose-built to evade Selenium/CDP detection on major anti-bot systems; uses the operator's real installed Chrome binary, giving an identical TLS and browser fingerprint to a genuine session
- Generally the strongest off-the-shelf anti-detection option for simple login-and-click flows without a paid proxy or fingerprint service
- Persistent Chrome profile support is straightforward — cookies and session state survive across runs, reducing login frequency
**Cons:**
- Diverges from the PRD-specified Playwright stack; adds Selenium and undetected-chromedriver on top of the existing environment
- undetected-chromedriver must be pinned to a specific Chrome version; Chrome auto-updates silently on macOS and can break the pairing between driver and browser binary with no warning
- Selenium's API is more verbose and synchronous; async patterns require explicit workarounds
- Playwright's richer semantic selectors (get_by_role, get_by_text) are unavailable — selector fragility increases, raising the maintenance burden when Craigslist changes its HTML
**Best if:** Bot detection proves to be a persistent and blocking problem with Playwright even after stealth patching, and the operator is willing to take on Chrome version pinning as an ongoing maintenance task.

## Design Document

### Components

- renew.py — Main entry point: parses CLI flags (--dry-run), wires together all modules, runs the top-level orchestration loop with single-retry logic, writes the final log entry, and exits with the correct code
- browser.py — Playwright session factory: launches headless Chromium (or applies stealth patches if that stack is chosen), sets a realistic viewport and user-agent string, and returns a configured page handle
- credentials.py — Secure credential retrieval abstraction: hides whether the active backend is macOS Keychain (via keyring library) or a chmod-600 .env file; chosen mechanism is [OPERATOR DECISION]
- auth.py — Login module: retrieves credentials via credentials.py, navigates to the Craigslist login URL, fills and submits the form, and asserts a logged-in state by checking the post-login URL or a logged-in DOM marker (e.g., presence of account menu)
- listings.py — Navigation and action module: navigates to the confirmed My Listings URL (see open_questions), locates the target tutoring listing row by title text, checks Renew button availability, enforces the NOT_YET_RENEWABLE guard, accepts any confirmation dialog, verifies the post-renewal success signal, and handles the dry-run bypass
- logger.py — Structured log writer: appends one record per run to a persistent local log file; mandatory fields: utc_timestamp (ISO-8601), outcome (SUCCESS / FAILURE / NOT_YET_RENEWABLE / DRY_RUN), step_number, error_type, stack_trace (null on success)
- setup.sh (optional, [could] tier) — One-command setup script: validates Python 3.11 and Playwright installation, installs the cron entry or launchd plist, and prints the confirmed schedule for operator review
- Scheduler entry — Either a crontab line or a launchd .plist in ~/Library/LaunchAgents with a 48-hour StartInterval; the scheduler choice is [OPERATOR DECISION] and is the single most architecturally significant configuration item

### Data Flow

TRIGGER (cron or launchd fires every 48 h) → renew.py invoked with optional --dry-run flag → credentials.py fetches username+password from Keychain or .env → browser.py opens headless Chromium page → auth.py navigates to Craigslist login URL, fills credentials, submits form, asserts logged-in DOM state → listings.py navigates to My Listings URL (direct URL preferred over dashboard clicking — see open_questions) → listings.py finds the tutoring listing row by title text → listings.py checks Renew button state: [ABSENT or DISABLED] → logger.py writes NOT_YET_RENEWABLE → exit 0; [PRESENT and ENABLED, dry-run=true] → logger.py writes DRY_RUN → exit 0; [PRESENT and ENABLED, dry-run=false] → listings.py clicks Renew → Playwright dialog listener accepts any confirm() popup → listings.py asserts success signal (banner text or timestamp change) → logger.py writes SUCCESS → exit 0. ON ANY EXCEPTION at any step: single automatic retry if the error is classified as transient (TimeoutError, NetworkError); if retry also fails → logger.py writes FAILURE record with step_number, error_type, full stack trace → exit non-zero → cron/launchd captures non-zero exit in system stderr log.

### Key Decisions

- Scheduler mechanism: cron vs. launchd plist — launchd with WakeForNetworkAccess is architecturally superior because standard cron does not fire on a sleeping Mac, which the PRD explicitly flags as a risk; this decision is [OPERATOR DECISION]
- Credential storage: macOS Keychain via keyring library vs. chmod-600 .env file — Keychain is more secure but can silently fail under a cron/launchd non-GUI session if the login Keychain is locked; .env is simpler and reliable under automation but puts credentials on disk; this is [OPERATOR DECISION]
- Anti-fingerprint strategy: directly coupled to tech stack choice — vanilla Playwright, Playwright+stealth, or Selenium+undetected-chromedriver; this is [OPERATOR DECISION]
- Post-login navigation path: direct URL navigation (e.g., accounts.craigslist.org/login/home) is preferred over clicking through a dashboard for reliability and speed; the exact URL must be confirmed by live inspection and then hardcoded or placed in a config variable — this is a discovery task before implementation can begin
- Renew button and listing-row selector strategy: text-based semantic selectors (Playwright get_by_text / get_by_role) are more resilient to Craigslist HTML refactors than CSS class selectors; recommended as the default approach, but final selectors require live DOM inspection by the operator or implementer
- Confirmation dialog type: native browser window.confirm() (handled automatically via Playwright page.on('dialog')) vs. an HTML modal overlay (requires a separate locator click) — must be determined by live inspection; impacts listings.py dialog-handling code
- Log file location and rotation policy: a fixed path under ~/Library/Logs/craigslist-renew/ is idiomatic on macOS; rotation strategy is [OPERATOR DECISION]
- Target listing identification: the script should identify the tutoring listing by title text match within the listings table; if Adi has multiple listings, a configurable title substring or listing ID must be set in config to avoid acting on the wrong row

### Open Questions

- [HANDOFF TO ARCHITECT — navigation path] The exact post-login URL and DOM structure of the Craigslist My Listings page cannot be resolved from the PRD alone. Discovery task (operator-assisted): log in manually to Craigslist, navigate to the listing management page, and record (a) the full stable URL — expected candidates are https://accounts.craigslist.org/login/home or a city-subdomain path like https://CITY.craigslist.org/mng; (b) whether the listing table loads synchronously in the page response or via a secondary XHR/fetch that requires an explicit wait; and (c) whether the direct manage URL for the specific tutoring listing (e.g., https://CITY.craigslist.org/mng/LISTING_ID) is a more reliable navigation target than the account dashboard. This URL must be confirmed before implementation of listings.py can begin.
- [HANDOFF TO ARCHITECT — Renew button selectors and success signal] Craigslist HTML class names are not stable across deployments. Discovery task (operator-assisted): open DevTools on the My Listings page and record (a) the element type and visible text of the Renew button — expected: a <button> or <a> element containing the text 'renew' (case-insensitive); (b) a sibling element or row attribute that uniquely identifies the tutoring listing row, such as the listing title text or a data-id attribute; (c) whether clicking Renew triggers a native browser window.confirm() dialog (Playwright handles this automatically) or an HTML modal overlay (requires an additional locator); and (d) the post-renewal success signal — expected candidates are a success banner containing text like 'Your post has been renewed', a URL change, or the listing's posted-date element updating to today's date. These findings directly determine the implementation of listings.py.
- Craigslist anti-bot posture for this specific account is unknown until first execution. If Craigslist begins presenting CAPTCHAs, the script exits non-zero and Adi must renew manually — this risks breaking the ≥95% success-rate acceptance criterion. The operator must explicitly accept this risk before implementation starts [see OPERATOR DECISIONS].
- 2FA and new-device login challenges: if Adi's Craigslist account triggers an email verification step when a headless browser session appears as a new device, the script cannot complete login and will fail at auth.py. The operator should confirm before implementation whether the account has any 2FA, email confirmation, or new-device challenge enabled, and if so, whether a persistent browser profile (saved cookies) can be used to pre-authenticate and avoid repeated login challenges.
- Whether the tutoring listing's direct manage URL is stable: the listing ID should not change on renewal (only on delete+repost), making a hardcoded direct URL a reliable and faster navigation target than scanning the dashboard table. Operator should record this URL as a config fallback.

## Operator Decisions

### [OPERATOR DECISION] [OPERATOR DECISION] Scheduler mechanism: cron vs. launchd

**Options:**
- macOS cron (crontab entry every 48 h): simpler to configure, universally understood, no plist file — does NOT fire when the Mac is asleep; missed fires are permanently lost with no catch-up
- macOS launchd (.plist in ~/Library/LaunchAgents with StartInterval=172800 and optionally WakeForNetworkAccess=true): more complex to configure as a plist file, but can wake the Mac from sleep to fire the job and optionally catches up missed runs — directly addresses the risk the PRD flags in assumptions
**Why it matters:** A sleeping Mac silently skips cron fires, which will break the ≥95% success-rate acceptance criterion if Adi's Mac sleeps during any 48-hour window. This is an irreversible architectural choice — switching from cron to launchd later requires rewriting the scheduler integration and setup script.

### [OPERATOR DECISION] [OPERATOR DECISION] Credential storage mechanism

**Options:**
- macOS Keychain via the 'keyring' Python library: credentials never touch the filesystem as plaintext; most secure — but Keychain access under a cron/launchd non-GUI session can silently fail if the login Keychain is locked (e.g., after a reboot before first login), causing auth.py to error rather than the renewal step
- chmod-600 .env file (readable only by Adi's OS user): simpler, no additional library dependency, works reliably under cron/launchd without any GUI or Keychain unlock dependency — credentials exist as plaintext on disk, protected only by filesystem permissions and full-disk encryption
**Why it matters:** Keychain silent failure under automated sessions is a real reliability risk that could cause the script to fail at the credentials step on every run after a reboot — breaking the acceptance criteria in a non-obvious way. This is a security vs. reliability tradeoff with no universally correct answer for a single-operator local script.

### [OPERATOR DECISION] [OPERATOR DECISION] Anti-fingerprint and anti-bot strategy (tied to tech stack choice)

**Options:**
- Vanilla Playwright (no stealth patches): simplest, already installed, zero maintenance overhead — accepted risk that Craigslist may eventually CAPTCHA the session
- Playwright + playwright-stealth: one additional pip dependency, patches most common automation signals — partial mitigation with some community-maintenance risk
- Selenium + undetected-chromedriver: strongest anti-detection, uses real Chrome binary — diverges from PRD-specified Playwright stack, introduces Chrome version pinning as an ongoing maintenance burden
**Why it matters:** If Craigslist's bot detection triggers a CAPTCHA, every affected run exits non-zero and Adi must manually renew once to reset the session. Frequent CAPTCHAs would break the ≥95% success-rate criterion. The choice made here directly determines how often human intervention will be required over the life of the system.

### [OPERATOR DECISION] [OPERATOR DECISION] Accept Craigslist Terms of Service / anti-automation risk

**Options:**
- Proceed with implementation: the script automates browser actions on Craigslist, which likely violates Craigslist's Terms of Service (automated access prohibition). Enforcement risk for a single personal listing renewed modestly (once every 48 h) is generally low, but Craigslist could flag the account, ghost the listing, or temporarily suspend posting privileges without notice
- Do not proceed: renew the listing manually every 48 hours via a browser
**Why it matters:** This risk is asymmetric and irreversible — if Craigslist flags and suspends the account or the listing, the tutoring post could be permanently lost and a new listing would need to be created. The operator must explicitly accept this risk before any implementation work begins.

### [OPERATOR DECISION] [OPERATOR DECISION] Log file rotation and retention policy

**Options:**
- No rotation: log file grows unbounded — at ~15 entries per month the file is small for years, but there is no automatic cleanup
- Python RotatingFileHandler (configurable maxBytes + backupCount): log is capped automatically at implementation time; runs beyond the cap are permanently lost
- Manual periodic pruning by Adi: no code required, operator clears or archives the log file as desired
**Why it matters:** Not a blocking pre-launch decision, but switching from no-rotation to a rotating handler after deployment requires a code change. Choosing a retention policy now avoids a later patch.

---

_Tier: Standard (agreed — credential handling, log persistence, scheduler integration, and Craigslist anti-automation surface clear the Micro bar). 3 tech stack options presented: vanilla Playwright, Playwright+stealth, Selenium+undetected-chromedriver. 5 operator decisions raised: scheduler mechanism (cron vs. launchd), credential storage (Keychain vs. .env), anti-fingerprint strategy, explicit ToS/account-suspension risk acceptance, and log rotation policy._
