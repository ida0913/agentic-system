# PRD — craigslist-repost-smoke

**Tier:** Standard  **Mode:** greenfield  **Complexity:** M  **Physical:** False

## Overview & Goals

Build a Playwright-based Python 3.11 script that automatically reposts Adi's Craigslist tutoring listing every 48 hours via a macOS cron job, keeping the listing near the top of search results with zero manual effort. Success means the listing timestamp refreshes reliably on schedule, the operator never has to interact with Craigslist manually for this task, and every run produces a clear log entry for audit.

## Problem Statement

Craigslist listings drop in search visibility within approximately 48 hours of posting. Manually reposting requires logging in, locating the listing, and clicking the repost button — a repetitive 3–5 minute task that must recur indefinitely every two days. Missing even one cycle means reduced exposure and lost tutoring inquiries, yet the task provides zero creative value.

## Target Audience

Internal — single operator (Adi)

## Success Metrics

- Repost succeeds on ≥ 95% of scheduled cron runs, measured by log file success-to-failure ratio over the first 30 days post-deployment.
- Each run completes (from cron trigger to confirmed repost and clean exit) in under 3 minutes, measured by timestamps in the log file.

## Features & Requirements

### Functional
- [must] Authenticate to Craigslist using credentials loaded at runtime from macOS Keychain (via the keyring library) — never from plaintext files
- [must] Navigate to the active tutoring listing and trigger Craigslist's built-in Repost flow
- [must] Confirm repost success by asserting the listing's displayed post date matches the current date after the repost action
- [must] Write a timestamped log entry (ISO-8601) for every run, recording outcome (SUCCESS or FAILURE) and run duration in seconds
- [should] Retry the repost once automatically on transient failure (network timeout, element-not-found) before marking the run as failed
- [could] Emit a macOS desktop notification via osascript on failure so Adi is alerted without checking the log
- [wont] Modify any listing content — title, body, and images are frozen and must not be touched by the script

### Non-functional
- [must] Run in Playwright headless mode so the script does not produce a visible browser window or interrupt active laptop work
- [must] Complete end-to-end in under 3 minutes under normal network conditions
- [must] Store credentials exclusively in macOS Keychain; no secrets in source code, config files, or crontab entries
- [should] Be idempotent: safe to re-invoke immediately if the cron daemon fires twice in the same window

### Usability
- [must] Single configuration file (e.g. config.toml excluded from version control) for the listing URL and any non-secret runtime settings
- [should] Log output uses a consistent human-readable format — ISO timestamp | level | message — for easy manual review

## User Journey

macOS cron job (launchd plist or crontab) fires every 48 hours → Python script starts, reads listing URL from config file, loads credentials from macOS Keychain → Playwright launches headless Chromium → Script navigates to Craigslist login page and authenticates → Script navigates to 'My Postings' and locates the active tutoring listing → [HANDOFF TO ARCHITECT] (decision: use Craigslist built-in Repost button flow vs. delete-and-resubmit; cookie or session-file persistence to reduce repeated full logins; CSS/XPath selector strategy for resilience against UI drift) → Script clicks the Repost button and steps through any confirmation dialogs → Script asserts the listing's post date is now today → Script writes a SUCCESS log entry with timestamp and duration and exits 0. On any failure: script logs FAILURE entry with error detail and stack trace, optionally fires macOS desktop notification, exits non-zero.

## Assumptions & Constraints

- Assumption: Craigslist does not hard-block headless Playwright automation for established accounts on the repost flow; no unsolvable CAPTCHA will appear under normal conditions. If CAPTCHA appears it is treated as a FAILURE, not handled.
- Assumption: The operator's laptop is awake and online when the cron window fires every 48 hours. No wake-on-schedule or laptop-sleep-management is in scope.
- Assumption: The existing Craigslist tutoring listing remains active (not flagged, removed, or expired). The script detects a missing listing as a FAILURE but does not attempt to create a new listing from scratch.
- Assumption: Notification preference is log-file-only by default (Q3 was answered with tech confirmation, not a notification preference); macOS desktop notification on failure is a 'could' feature, not 'must'.
- Assumption: Single listing only, inferred from singular phrasing in the request and the simple cron approach confirmed in A4.
- Constraint: No Craigslist API exists; browser automation via Playwright is the only integration path.
- Constraint: Python 3.11 and Playwright are already installed on the operator's machine; no new runtimes are introduced.
- Constraint: All secrets must live in macOS Keychain; nothing sensitive may appear in any committed or plaintext file.

## Competitive Context

N/A — internal

## Out of Scope

- Reposting multiple listings or listings across different cities
- Cloud, VPS, or server deployment; execution is exclusively local on the operator's laptop
- Slack, email, SMS, or push notification integrations
- Editing or updating any listing content (title, body, images, price, category)
- CAPTCHA solving or account-recovery flows
- Support for any classifieds platform other than Craigslist
- A management UI or dashboard for the script
- Delete-and-resubmit as a fallback path — if the Repost button is absent, the run is logged as FAILURE

## Acceptance Criteria

1. AC-1: Given valid credentials and an active listing, the script completes the repost and the listing's displayed post date matches the current date within 60 seconds of script invocation — verified by the script's own post-run DOM assertion.
2. AC-2: Given a simulated network failure on the first attempt, the script retries exactly once; if the retry also fails, it writes a FAILURE log entry containing the error message and exits with a non-zero return code.
3. AC-3: The cron job fires at the correct 48-hour cadence — verified by inspecting log entry timestamps across at least 3 consecutive successful runs showing ~48-hour gaps.
4. AC-4: No plaintext credentials appear in any script file, config file, crontab entry, or git history — verified by grep scan of the project directory and crontab before sign-off.
5. AC-5: The script completes entirely in headless mode with no visible browser window — verified by observer check during a manual test invocation.
6. AC-6: Every run produces exactly one log entry containing the ISO-8601 run timestamp, outcome label (SUCCESS or FAILURE), and run duration in whole seconds.

## DMAIC Plan

### Define
**Owner:** PM  **Entry:** Operator request received and clarifying answers collected.  **Exit:** Define package reviewed and approved by operator; classification, scope, and all acceptance criteria are locked. Complexity: S.

- Approved PRD with locked acceptance criteria
- SIPOC and CTQ tree
- Dual-mode DMAIC plan with owner and entry/exit criteria per phase

### Measure
**Owner:** PM  **Entry:** Define phase exit criteria met.  **Exit:** Baseline numbers documented in the project log; manual effort cost quantified and agreed as the improvement benchmark. Complexity: S.

- Manual baseline recorded: average wall-clock time Adi spends per manual repost session (target unit: seconds)
- Frequency audit: how many repost cycles occur per month and how often the cycle is missed or late
- Calculated monthly manual effort displaced by this automation (minutes/month)
- Estimated cost of missed reposts in lost tutoring inquiries (qualitative if not quantifiable)

### Analyze
**Owner:** Claude (general-purpose agent)  **Entry:** Measure baseline documented.  **Exit:** Repost UI flow fully mapped; all failure modes catalogued with handling strategy; no open unknowns blocking implementation. Complexity: S.

- Craigslist repost UI flow mapped: exact page sequence, button selectors, form fields, and confirmation signals
- Failure mode catalog: login failure, listing-not-found, Repost button absent, CAPTCHA trigger, session expiry, network timeout
- Selector fragility assessment: stable vs. drift-prone DOM targets
- Cookie/session persistence feasibility: whether storing a Playwright session file avoids repeated full logins
- Credential storage option analysis confirming macOS Keychain via keyring as the approach

### Improve
**Owner:** Plan agent  **Entry:** Analyze failure modes and UI map complete.  **Exit:** Architecture plan reviewed and approved; all acceptance-criteria-mapped design decisions resolved; implementation can begin without ambiguity. Complexity: M.

- Detailed script architecture: module breakdown (auth, navigate, repost, confirm, log), retry logic design, logging schema
- Credential storage design: keyring integration pattern and one-time enrollment flow
- macOS scheduling spec: launchd plist vs. crontab comparison and recommended configuration for 48-hour cadence
- Headless Playwright session design: cookie-reuse strategy vs. fresh login per run, tradeoffs documented

### Implement
**Owner:** Claude (general-purpose agent)  **Entry:** Improve architecture plan approved by PM.  **Exit:** All 6 acceptance criteria pass on the operator's machine; 3 consecutive timed runs succeed; no secrets in plaintext anywhere. Complexity: M.

- Python 3.11 Playwright script: login, navigate, repost, confirm, log — passing all AC-1 through AC-6
- macOS launchd plist (or crontab entry) configured for 48-hour cadence
- One-time Keychain credential enrollment script or step-by-step setup instructions
- 3 consecutive cron-triggered test runs with SUCCESS log entries and verified listing timestamp updates
- grep scan confirming zero plaintext credentials in project directory and crontab

### Control
**Owner:** PM  **Entry:** Implement phase exit criteria met; script live on production cron schedule.  **Exit:** All control artifacts documented; operator confirms understanding of maintenance procedures and failure SOP. Complexity: S.

- Log review cadence SOP: operator checks log file weekly; alert threshold defined (2 consecutive FAILUREs = manual intervention)
- Selector update protocol: step-by-step procedure for updating CSS/XPath selectors if Craigslist changes its UI
- Failure response SOP: what Adi does when a FAILURE log entry or desktop notification appears
- requirements.txt with pinned dependency versions to prevent drift
- Scheduled 90-day script health check reminder

## SIPOC

**Suppliers**
- macOS cron daemon (launchd) — provides the 48-hour schedule trigger
- macOS Keychain — supplies Craigslist credentials at runtime via the keyring library
- Craigslist web application (craigslist.org) — hosts the listing and repost UI
- Playwright + Chromium — browser automation engine executing the repost flow

**Inputs**
- Craigslist account credentials (username + password, loaded from macOS Keychain)
- Active tutoring listing URL or 'My Postings' page URL (from config file)
- 48-hour cron trigger signal from launchd
- Live network connection to craigslist.org

**Process**
- 1. macOS cron fires the Python script
- 2. Script reads config file for listing URL; loads credentials from macOS Keychain
- 3. Playwright launches headless Chromium
- 4. Script navigates to Craigslist login page and authenticates
- 5. Script navigates to the active tutoring listing via 'My Postings'
- 6. Script clicks the Repost button and steps through any confirmation dialogs
- 7. Script asserts the listing's new post date equals today's date
- 8. Script writes a timestamped log entry (SUCCESS or FAILURE) and exits

**Outputs**
- Craigslist tutoring listing with a refreshed (current-day) post timestamp
- Timestamped log entry recording outcome and run duration
- Optional: macOS desktop notification on failure

**Customers**
- Adi — benefits from the listing remaining visible in Craigslist search results without any manual effort

## CTQ Tree

- **Need:** Tutoring listing stays near the top of Craigslist search results → **Driver:** Listing must be reposted every 48 hours without any manual intervention → **Target:** ≥ 95% of scheduled cron runs result in a confirmed successful repost over any rolling 30-day window (max 1 failure per 20 runs)
- **Need:** Automation runs silently without disrupting laptop work → **Driver:** Script must execute entirely in headless mode and finish in a short, bounded time → **Target:** 100% of runs use headless Playwright with no visible browser window; every run completes in under 3 minutes as recorded in the log
- **Need:** Craigslist credentials remain secure at all times → **Driver:** Login credentials must never be exposed in plaintext in any file, script, or shell history → **Target:** Zero plaintext credential occurrences detected by grep scan of the project directory and crontab at deploy time and at each 90-day control check

---

_Craigslist tutoring-listing auto-reposter: a Python 3.11 + Playwright script that logs in and clicks Repost every 48 hours via macOS cron, eliminating a recurring 3–5 min manual task with secure credential storage and structured logging. | Tier: Standard | Mode: greenfield | Size: M | 6 DMAIC phases (Define → Measure → Analyze → Improve → Implement → Control)._
