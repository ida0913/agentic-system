# PRD — architect-smoke

**Tier:** Standard  **Mode:** greenfield  **Complexity:** S  **Physical:** False

**Committed operation:** Clicking the Craigslist Renew button on the active tutoring listing every 48 hours

## Overview & Goals

Build a Python 3.11 / Playwright script, scheduled via macOS cron, that logs in to Craigslist and clicks the Renew button on Adi's active tutoring listing every 48 hours to keep the post timestamp current. The system refreshes the post timestamp only; it does NOT delete, recreate, edit, or duplicate the listing in any way. Success means the listing reliably reappears near the top of Craigslist search results without any manual browser interaction from Adi.

## Problem Statement

Craigslist deprioritizes older posts in search results; the only way to restore visibility is to click the Renew button every 48 hours. Doing this manually requires Adi to remember the exact 48-hour window, open a browser, log in, and click through the UI — a small but recurring interruption that is frequently missed or delayed, causing the tutoring listing to fall in rankings and reduce inbound student inquiries.

## Target Audience

Internal — single operator (Adi)

## Success Metrics

- ≥ 95% of scheduled 48-hour renewal attempts complete successfully (Renew button clicked and confirmed by Craigslist) over any rolling 30-day window (≥ 14 of 15 expected runs)
- Script runtime per run ≤ 120 seconds from cron trigger to final log write under normal network conditions
- 100% of failed runs produce a structured local log entry within 60 seconds of the failure event, with a non-zero exit code captured by the macOS cron error channel

## Features & Requirements

### Functional
- [must] Schedule-triggered Python/Playwright script that launches a headless Chromium session, logs in to Craigslist with stored credentials, navigates to the active tutoring listing, and clicks the Renew button
- [must] Secure credential storage — credentials must not reside in plain-text source files; macOS Keychain or a permissions-restricted .env file (chmod 600) are acceptable approaches; final mechanism deferred to Architect phase
- [must] Structured local log file capturing per run: UTC timestamp, outcome label (SUCCESS / FAILURE / NOT_YET_RENEWABLE), step number at failure, error type, and full stack trace on failure
- [must] Non-zero exit code on any unrecoverable failure so macOS cron captures the event in system logs
- [should] Guard condition: if the Renew button is absent or disabled (listing renewed < 48 h ago), log 'NOT_YET_RENEWABLE' and exit with code 0 without treating the run as a failure
- [should] Single automatic retry on transient network errors or element-not-found timeouts before marking the run as FAILURE
- [could] --dry-run CLI flag that completes all navigation steps up to but not including clicking Renew, then logs 'DRY RUN — no action taken' and exits 0
- [could] One-command setup script that installs the cron entry, validates Python 3.11 and Playwright prerequisites, and prints the installed schedule for Adi to confirm
- [wont] CAPTCHA solving or any bot-detection bypass — if a CAPTCHA is encountered the script logs 'CAPTCHA_DETECTED' and exits non-zero

### Non-functional
- [must] Runs fully headless — no visible browser window during scheduled cron execution
- [must] Script completes within 120 seconds under normal home-network conditions
- [must] Credentials never written to unprotected plain-text disk files at any point in the execution path
- [should] Script is idempotent — running it a second time within the 48-hour lock window produces the NOT_YET_RENEWABLE outcome, not an error or duplicate renewal

### Usability
- [could] --dry-run flag lets Adi verify the full browser flow against the live Craigslist UI without submitting any renewal action
- [could] Human-readable log format (ISO-8601 timestamps, clear outcome labels) reviewable with 'tail -f' or any text editor
- [could] Setup script prints a confirmation summary of the installed cron schedule so Adi can visually verify the interval before the first live run

## User Journey

TRIGGER: macOS cron fires at the configured 48-hour interval. → STEP 1: Python script launches a headless Playwright (Chromium) browser session. → STEP 2: Script navigates to the Craigslist login page and authenticates using credentials retrieved from secure storage. → STEP 3: Script navigates to the 'My Account / My Listings' page (or a direct listing URL if more reliable). [HANDOFF TO ARCHITECT: confirm the exact post-login navigation path; determine whether Craigslist redirects to a dashboard or requires an extra click to reach the listings table.] → STEP 4: Script locates the active tutoring listing row in the listings table. → STEP 5: Script checks whether the Renew button is currently active/clickable. If not available, logs NOT_YET_RENEWABLE and exits 0. → STEP 6: Script clicks the Renew button and handles any confirmation dialog (e.g., clicks the confirm/OK button). [HANDOFF TO ARCHITECT: identify stable CSS or XPath selectors for the Renew button and any confirmation dialog; identify the post-renewal confirmation signal — success banner text, URL change, or timestamp element update.] → STEP 7: Script verifies the renewal success signal. → STEP 8: Script writes a structured SUCCESS log entry and exits 0. → ON ANY FAILURE (any step above): script catches the exception after optional single retry, writes a structured FAILURE log entry with step number, error type, and stack trace, and exits non-zero.

## Assumptions & Constraints

- Assumption: Adi has a registered Craigslist account (email + password); the system requires access to the 'My Listings' dashboard, which is only available to logged-in registered users — anonymous one-off post flows are out of scope
- Assumption: Q1 (renew vs. delete-and-recreate) was answered obliquely via A2 ('only the post timestamp needs refreshing'); this is interpreted as definitively selecting the Renew button flow, not listing recreation
- Assumption: Q4 (failure handling) was not answered; default behavior is local log-only with non-zero exit code — no active alerting (Slack, email, push) in this release; this can be added post-release
- Assumption: The Mac is awake, logged in as Adi, and connected to the internet at cron fire time; sleep/wake management is the operator's responsibility — missed cron fires due to sleep are not recovered automatically
- Constraint: Craigslist has no public API; all interaction is via Playwright browser automation against the live Craigslist HTML, which may change without notice and could break selectors
- Constraint: No CAPTCHA-solving service is in scope; any CAPTCHA halts the run and requires Adi to manually renew once before the bot resumes
- Constraint: Craigslist enforces a 48-hour lock between renewals; the script must tolerate the button being unavailable as a non-error condition
- Constraint: Python 3.11 and Playwright are already installed on the operator's Mac; no runtime installation is required, only project-level dependencies
- Constraint: macOS cron does not wake a sleeping machine; the Architect phase must evaluate launchd (with WakeForNetworkAccess) as a more reliable scheduler alternative

## Competitive Context

N/A — internal

## Out of Scope

- Delete-and-repost / listing recreation — the system does NOT delete the existing listing and submit a new one under any circumstance
- Editing or updating listing content — title, body text, images, category, price, and contact information are never read, modified, or resubmitted
- Cloud or server deployment — no VPS, Docker container, cloud function, GitHub Actions, or any remote scheduler; local macOS cron only
- Cross-platform execution — macOS only; no Windows or Linux support in this release
- Multi-listing management — only the single active tutoring listing is targeted; generalization to other listings is not in scope
- Posting to any platform other than Craigslist (e.g., Facebook Marketplace, Nextdoor, Wyzant)
- CAPTCHA solving or bypass of any Craigslist bot-detection or rate-limiting mechanism
- Active failure notifications (Slack, email, SMS, push notification) — local log file and cron stderr only in this release
- Automatic credential rotation, 2FA handling, or OAuth flows
- Any mobile automation via iOS or Android Craigslist apps

## Acceptance Criteria

1. AC-1 [Renewal success]: Given valid stored credentials and an active tutoring listing whose Renew button is available, when the script runs, the listing timestamp on Craigslist updates to the current date, a SUCCESS entry appears in the local log file, and the script exits 0 — all within 120 seconds of invocation.
2. AC-2 [Not-yet-renewable guard]: Given the listing was renewed less than 48 hours ago (Renew button absent or disabled), when the script runs, it exits with code 0, writes a NOT_YET_RENEWABLE log entry, and performs no click actions on the page.
3. AC-3 [Failure logging]: Given any unrecoverable error (login failure, selector not found after retry, unexpected page state, CAPTCHA detected), the script exits with a non-zero status code and the log file contains a structured FAILURE entry including UTC timestamp, step number, error type, and full stack trace.
4. AC-4 [Dry-run mode]: Given the --dry-run flag, the script completes all navigation and verification steps up to but not including clicking Renew, logs 'DRY RUN — no action taken,' exits 0, and the Craigslist listing timestamp is unchanged.
5. AC-5 [Headless execution]: When invoked via the installed cron entry (no interactive terminal), the script runs to completion without opening any visible browser window, confirmed by macOS window manager inspection during a test run.
6. AC-6 [Cron scheduling fires correctly]: The installed cron entry (or launchd plist) fires the script within ±5 minutes of the target 48-hour interval on a non-sleeping Mac, verified across at least 2 consecutive successful cycles in the operator's environment.

## DMAIC Plan

### Define
**Owner:** PM  **Entry:** Operator has answered clarifying questions  **Exit:** PRD reviewed and accepted by Adi; resolved operation committed; no open scope ambiguities

- PRD with resolved operation, scope boundaries, and acceptance criteria
- SIPOC diagram
- CTQ tree
- Classification (tier / mode / complexity / physical)

### Measure
**Owner:** Architect  **Entry:** Define phase exit: PRD accepted by Adi  **Exit:** Manual baseline documented with time estimates; at least two stable selector candidates for the Renew button and confirmation signal confirmed via browser DevTools inspection on the live site

- Manual baseline: estimated time per renewal session (login → navigate → click → confirm), estimated weekly time cost, and qualitative miss-rate (how often the 48-hour window lapses before Adi renews manually)
- Craigslist UI audit: live browser inspection recording of the full manual renewal flow — login page URL, post-login redirect path, 'My Listings' page URL, Renew button HTML attributes and at least two stable selector candidates, confirmation dialog markup and selector
- Confirmation signal inventory: identify the success indicator Craigslist returns after renewal (banner text, URL change, timestamp element update)
- Risk register: observed CAPTCHA frequency, login session cookie lifespan, estimated Craigslist HTML change cadence

### Analyze
**Owner:** Architect  **Entry:** Measure exit: baseline documented and selectors confirmed  **Exit:** All critical failure modes have assigned mitigations; scheduling mechanism (cron vs. launchd) decided with documented rationale

- Failure mode and effects analysis (FMEA) covering: CAPTCHA appearance, Craigslist HTML/selector drift, macOS sleep/wake scheduling gaps, login session expiry, 48-hour lock detection edge cases
- Selector stability assessment: rank candidate selectors by fragility; recommend primary and fallback selectors
- Scheduling mechanism decision: cron vs. launchd (with WakeForNetworkAccess) evaluated for reliability on a Mac that may sleep overnight; recommendation with rationale
- Mitigation strategy assigned to each identified failure mode

### Improve
**Owner:** Architect  **Entry:** Analyze exit: all failure modes mitigated and scheduling mechanism decided  **Exit:** Design document reviewed and approved by Adi; Engineer handoff package is complete and self-contained — no further design decisions required from Engineer

- Script architecture design document: module breakdown (auth, navigator, renewer, logger, retry handler), credential storage mechanism (Keychain vs. restricted .env), dry-run flag interface specification
- Logging schema definition: field names, types, and example entries for SUCCESS / FAILURE / NOT_YET_RENEWABLE / DRY_RUN outcomes
- Scheduler configuration design: cron expression or launchd .plist template, stdout/stderr capture method, environment variable passing strategy
- Engineer handoff package: design doc + ranked selector list + credential storage spec + confirmation signal spec

### Implement
**Owner:** Engineer  **Entry:** Improve exit: Engineer handoff package delivered  **Exit:** All six acceptance criteria (AC-1 through AC-6) pass on Adi's machine; first live renewal run produces a SUCCESS log entry with timestamp matching current date on Craigslist

- Python 3.11 / Playwright renewal script satisfying all functional and non-functional requirements
- Credential storage integration per Architect-specified mechanism (Keychain or restricted .env)
- Structured local log file with all schema-defined fields per run
- --dry-run flag implementation
- macOS cron entry or launchd .plist installed and smoke-tested
- Setup script (one-command installation and prerequisite validation)
- README with first-run verification steps and log file location

### Control
**Owner:** Engineer / Adi  **Entry:** Implement exit: all acceptance criteria passed on operator's machine  **Exit:** 5 consecutive successful renewal runs logged with no manual intervention; runbook reviewed and accepted by Adi; system declared operational

- First-5-runs monitoring log: outcome, runtime, anomalies, and Adi sign-off for each of the first five scheduled runs
- Runbook covering operator response to: CAPTCHA detected, Renew button selector broken by UI change, credential rotation needed, cron/launchd fire missed because Mac was asleep
- Weekly log review checklist: 30-second procedure for Adi to confirm the most recent run succeeded
- Go/no-go sign-off memo after 5 consecutive successful runs

## SIPOC

**Suppliers**
- macOS system clock / cron scheduler or launchd (provides the 48-hour trigger)
- Craigslist web UI (target system supplying the Renew button and confirmation signal)
- Adi (supplies account credentials and the initial listing)
- Python 3.11 runtime (pre-installed on operator's Mac)
- Playwright / Chromium browser engine (pre-installed on operator's Mac)

**Inputs**
- 48-hour cron or launchd trigger signal
- Craigslist account email and password retrieved from secure credential storage
- Craigslist 'My Listings' page URL or direct listing URL
- Playwright browser context and Chromium session
- CSS / XPath selectors for the Renew button and confirmation signal (hardcoded from Measure phase)

**Process**
- 1. cron / launchd fires the Python script at the scheduled 48-hour interval
- 2. Script launches a headless Chromium session via Playwright
- 3. Script navigates to Craigslist login page and authenticates with stored credentials
- 4. Script navigates to 'My Account / My Listings' page
- 5. Script locates the active tutoring listing row
- 6. Script checks Renew button availability; logs NOT_YET_RENEWABLE and exits 0 if unavailable
- 7. Script clicks Renew button and confirms any resulting dialog
- 8. Script verifies the post-renewal confirmation signal
- 9. Script writes structured log entry (SUCCESS / FAILURE) and exits with appropriate code

**Outputs**
- Refreshed listing timestamp on Craigslist (primary business outcome — listing surfaces near top of search results)
- Structured local log entry per run with outcome label, UTC timestamp, runtime, and error details on failure
- Non-zero exit code on failure (captured by macOS cron / launchd error channel for passive monitoring)

**Customers**
- Adi (sole operator) — benefits from sustained tutoring listing visibility and elimination of the manual 48-hour renewal task

## CTQ Tree

- **Need:** Tutoring listing stays visible near the top of Craigslist search results at all times → **Driver:** Renewal fires reliably on the 48-hour cycle without missed or delayed runs → **Target:** ≥ 95% of scheduled renewal attempts succeed over any rolling 30-day window (≥ 14 of 15 expected runs complete with a SUCCESS log entry)
- **Need:** Operator is not burdened with manual monitoring or surprise gaps in listing visibility → **Driver:** Every failure is immediately captured and surfaced through passive system channels without Adi needing to proactively check → **Target:** 100% of failed runs produce a structured FAILURE log entry within 60 seconds of the error event; script exits non-zero so cron/launchd error email fires automatically
- **Need:** Automation is fast and unobtrusive during normal laptop use → **Driver:** Script runs headless and completes quickly without competing for system resources → **Target:** Script runtime ≤ 120 seconds per run; zero visible browser windows opened during any scheduled execution

---

_Headless Playwright + Python 3.11 cron bot that clicks the Craigslist Renew button on Adi's tutoring listing every 48 h — timestamp refresh only; no delete, recreate, or content edits; runs locally on Adi's Mac.
Tier: Standard | Mode: Greenfield | Complexity: S | Physical: false
6-phase DMAIC plan: Define → Measure (manual baseline + UI audit) → Analyze → Improve → Implement → Control_
