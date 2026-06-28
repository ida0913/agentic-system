# PRD — craigslist-repost-smoke

**Tier:** Standard  **Mode:** greenfield  **Complexity:** M  **Physical:** False

**Committed operation:** Renew existing Craigslist tutoring listing timestamp by clicking the Renew button every 48 hours

## Overview & Goals

The system automates renewal of a single, existing Craigslist tutoring listing by clicking the platform's native Renew button every 48 hours via a Playwright script triggered by macOS cron. Success means the listing's post timestamp is refreshed on schedule without any manual operator action. The system does NOT delete, recreate, or duplicate the listing — it performs only the timestamp-renewal action Craigslist provides for active postings. Listing content (title, body, price, images) is never read, modified, or re-submitted.

## Problem Statement

Craigslist demotes listings over time as newer posts appear above them in search results. To stay visible, the operator must manually log in and click Renew every 48 hours — a repetitive 2–5 minute task that is easy to forget, causing the listing to fall in ranking and reducing inbound tutoring inquiries.

## Target Audience

Internal — single operator (Adi)

## Success Metrics

- Renew action completes successfully on ≥ 95% of scheduled 48-hour cycles, measured via the local log file over any rolling 30-day period
- Total manual intervention time for routine renewals reduced to < 5 minutes per month, down from an estimated 60–70 minutes per month of fully manual renewal

## Features & Requirements

### Functional
- [must] Playwright script authenticates to Craigslist using credentials loaded from a local .env file and navigates to the active tutoring listing's management page
- [must] Script locates and clicks the Renew button when the listing is eligible; if the button is absent (cooldown not elapsed), the run is recorded as SKIP and exits cleanly with code 0
- [must] Every run appends a structured log entry (ISO timestamp, outcome: SUCCESS | FAILURE | SKIP, error detail if applicable) to a local plain-text log file
- [must] macOS cron job configured to invoke the script every 48 hours
- [should] On any FAILURE outcome, fire a macOS terminal notification (via osascript) with a human-readable reason (e.g., 'CAPTCHA detected', 'Renew button not found', 'Login failed')
- [could] Persist Playwright browser session cookies to disk between runs to reduce login frequency and CAPTCHA exposure
- [wont] Modify listing content (title, body, price, images) in any cycle
- [wont] Automated CAPTCHA solving of any kind

### Non-functional
- Script must run fully unattended — no stdin, GUI prompt, or user interaction required under normal conditions
- Credentials stored exclusively in a local .env file or macOS Keychain; never hardcoded in source
- Script exits with a non-zero return code on FAILURE so cron and the operator can detect the error state
- Log file must not grow unbounded; entries older than 30 days should be pruned or the file rotated on each run

### Usability
- A single README explains how to configure credentials, install dependencies, register the cron job, and interpret log entries
- Failure terminal notification must state the specific reason in plain English so the operator knows whether to act immediately

## User Journey

TRIGGER: macOS cron fires the script every 48 hours.
1. cron invokes `python renew_listing.py`.
2. Script reads Craigslist credentials from .env (or Keychain).
3. Playwright launches a browser (headless vs. headed TBD by risk of CAPTCHA — [HANDOFF TO ARCHITECT]) and navigates to the Craigslist login page.
4. Script submits login credentials and confirms successful authentication.
5. Script navigates to 'My Account → Active Postings' and locates the tutoring listing by stored listing ID or URL.
6. Script checks for the presence of the Renew button. If absent (listing not yet eligible): writes SKIP log entry, exits with code 0.
7. If Renew button present: script clicks it and waits for the confirmation state (page feedback or URL change confirming renewal).
8. Script appends a SUCCESS entry (ISO timestamp, listing ID) to the local log file and exits with code 0.
9. On any exception, unexpected page state, or CAPTCHA detection at any step: script appends a FAILURE entry with reason to the log file, fires a macOS osascript notification with the reason string, and exits with a non-zero code.
OUTPUT: Listing post timestamp refreshed on Craigslist; log file updated; operator notified only on failure.

## Assumptions & Constraints

- ASSUMPTION: The Craigslist account does not use two-factor authentication or SMS verification — the operator did not confirm this in response to Q2; if 2FA is active, cookie-session persistence becomes mandatory and the authentication flow must be re-scoped before Improve phase
- ASSUMPTION: This is a single listing in a single Craigslist city and category — the operator did not confirm multi-city scope in response to Q5; conservative single-listing interpretation is committed
- The listing is already live and active; the script is not responsible for creating a new listing if the existing one is removed or expires
- The operator's MacBook must be awake, logged in, and connected to the internet at the time cron fires; if the machine is asleep, the cron job will not execute and no retry mechanism is in scope
- Playwright 1.x is already installed in the Python 3.11 environment (confirmed by operator)
- Craigslist may present CAPTCHA challenges at login or on navigation; the script will detect and log these but will NOT attempt to solve them — CAPTCHA incidents count as FAILURE and require manual operator intervention
- Craigslist's DOM structure and CSS selectors may change without notice; selector maintenance after breakage is the operator's responsibility
- The Craigslist Renew button enforces a platform-side cooldown (typically 48 hours); runs before the cooldown elapses will encounter an absent button and will be logged as SKIP, not FAILURE

## Competitive Context

N/A — internal

## Out of Scope

- Delete-and-repost / listing recreation: the system renews an existing post only; it does not remove and re-create the listing under any circumstance
- Editing or updating listing content (title, body, price, images) between or during cycles
- Posting across multiple Craigslist cities, categories, or accounts
- Automated CAPTCHA solving or bypass of any kind
- Cloud or server deployment; the system runs exclusively on the operator's local macOS machine
- Managing multiple listings simultaneously
- Remote notifications via Slack, email, or SMS — only a local macOS terminal notification is in scope (as a should-have)
- Retry logic within a single failed cycle; each cron invocation is one attempt

## Acceptance Criteria

1. Given valid credentials and a renewal-eligible listing, after the script runs the listing's post date on Craigslist equals today's date — verifiable by loading the listing URL in a browser
2. Given a successful renewal, the local log file contains a new line with outcome=SUCCESS and an ISO 8601 timestamp within 5 seconds of the actual run time
3. Given a login failure (wrong credentials or unexpected login page state), the log contains outcome=FAILURE with a reason string, and the script exits with a non-zero code
4. Given that the Renew button is not present on the listing management page (cooldown not elapsed), the log contains outcome=SKIP and the script exits with code 0 — the listing is NOT modified
5. Given a CAPTCHA page appearing at any navigation step, the log contains outcome=FAILURE with reason 'CAPTCHA detected', a macOS notification fires with that reason, and the script exits with a non-zero code
6. Given the cron entry is registered, the script is invoked automatically at the correct 48-hour interval without any manual trigger — confirmed by two consecutive log entries separated by 47–49 hours

## DMAIC Plan

### Define
**Owner:** PM  **Entry:** Operator has answered all clarifying questions  **Exit:** PRD reviewed and approved by Adi; all assumptions acknowledged; scope commitment recorded

- PRD with committed resolved_operation and scope exclusions
- SIPOC diagram
- CTQ tree
- Dual-mode DMAIC plan
- Operator sign-off on scope (especially single-listing, no-2FA assumptions)

### Measure
**Owner:** Adi (self-report) + Engineer (process observation)  **Entry:** Define phase complete and signed off  **Exit:** Manual baseline documented in minutes per month; Craigslist renewal page flow mapped with screenshots of each step and the Renew button state

- Manual baseline: operator self-reports actual time spent per manual renewal cycle and approximate monthly forget/miss rate
- Estimated monthly manual effort baseline in minutes (target for comparison post-deploy)
- Observation of the Craigslist renewal flow by hand: steps required, pages visited, button labels, confirmation signals — documented as the process map the script must replicate

### Analyze
**Owner:** Architect  **Entry:** Measure phase complete; process map and manual baseline available  **Exit:** Top 3 failure modes have documented mitigations; headless/headed decision made; selector strategy chosen

- Failure mode and effects analysis (FMEA) covering: CAPTCHA at login, selector drift, laptop asleep at cron time, session expiry, Renew button absent, network timeout
- Risk register with severity × likelihood ranking for each failure mode
- Decision on headless vs. headed Playwright mode (CAPTCHA risk trade-off)
- Selector strategy recommendation (CSS vs. ARIA roles vs. text matching for resilience)

### Improve
**Owner:** Engineer  **Entry:** Analyze phase complete; failure modes and selector strategy decided  **Exit:** Script executes all three outcome paths (SUCCESS, SKIP, FAILURE) and produces correct log entries and exit codes; peer-reviewed by Adi

- Playwright Python script implementing: credential loading, login, listing navigation, Renew-button detection, click, confirmation check, structured log append, CAPTCHA detection, macOS osascript notification on failure, clean exit codes
- .env template file with required credential variables
- Optional: cookie-session persistence module
- Unit-testable helper functions for log writing and notification dispatch
- Local end-to-end test run against a real or staging Craigslist session verifying SUCCESS, SKIP, and FAILURE paths

### Implement
**Owner:** Engineer + Adi  **Entry:** Improve phase complete; script tested and signed off  **Exit:** First unattended renewal cycle completes successfully; SUCCESS log entry written; operator confirms listing post date updated

- cron entry registered on operator's MacBook (crontab -e or launchd plist)
- README covering: dependency install, .env setup, cron registration, log location, and how to read notification messages
- Credentials configured and verified by operator
- First live automated renewal cycle observed and log entry confirmed by Adi

### Control
**Owner:** Adi  **Entry:** Implement phase complete; first live cycle verified  **Exit:** 5 consecutive successful 48-hour renewal cycles logged with no manual intervention; success rate KPI baseline established

- Operator habit established: weekly 30-second log review to confirm ongoing SUCCESS/SKIP entries
- Selector maintenance runbook: how to identify a broken selector from a FAILURE log entry and update the script
- 30-day success-rate report from log file confirming ≥ 95% successful cycles
- Handoff checklist: what to do if CAPTCHA appears, if the listing expires, or if macOS version update breaks Playwright

## SIPOC

**Suppliers**
- Craigslist web platform (listing management UI — source of the Renew button and confirmation state)
- macOS system cron daemon (schedule trigger every 48 hours)
- Local .env file or macOS Keychain (Craigslist credentials)
- Playwright Python library (browser automation runtime, already installed)

**Inputs**
- Craigslist account username and password
- Listing URL or listing ID for the tutoring post
- 48-hour cron schedule expression
- Playwright browser context (session cookies, optional persisted state)

**Process**
- 1. cron fires the Python script on schedule
- 2. Script loads credentials from .env / Keychain
- 3. Playwright opens browser and navigates to Craigslist login
- 4. Script authenticates and confirms login success
- 5. Script navigates to Active Postings and locates the tutoring listing
- 6. Script checks for Renew button availability
- 7a. If eligible: script clicks Renew and waits for confirmation — outcome SUCCESS
- 7b. If not eligible (cooldown): script exits cleanly — outcome SKIP
- 7c. If any error or CAPTCHA: script detects failure state — outcome FAILURE
- 8. Script appends structured log entry with outcome and timestamp
- 9. On FAILURE: script fires macOS osascript notification with reason string
- 10. Script exits with appropriate return code

**Outputs**
- Refreshed listing post timestamp on Craigslist (SUCCESS path)
- Local log file entry (SUCCESS | SKIP | FAILURE) with ISO timestamp and detail
- macOS terminal notification (FAILURE path only)

**Customers**
- Adi (operator — benefits from increased listing visibility and zero manual renewal effort)

## CTQ Tree

- **Need:** Tutoring listing stays near the top of Craigslist search results → **Driver:** Listing timestamp must be renewed on the 48-hour schedule without gaps or missed cycles → **Target:** ≥ 95% of scheduled 48-hour renewal cycles result in a SUCCESS or valid SKIP log entry, measured over any rolling 30-day window
- **Need:** Zero manual effort for routine listing maintenance → **Driver:** Script runs fully unattended; operator never needs to log in manually for a routine renewal → **Target:** < 5 minutes per month of manual operator time attributable to renewal tasks (excluding extraordinary CAPTCHA intervention events)
- **Need:** Operator is informed promptly when automation fails → **Driver:** Failure notifications must be timely, specific, and require no log-file digging to understand → **Target:** macOS notification fires within 60 seconds of a FAILURE exit; notification text names the specific failure reason; log entry written for 100% of runs regardless of outcome

---

_Playwright + macOS cron script that renews (timestamp-refreshes) a single existing Craigslist tutoring listing every 48 hours — it does NOT delete or repost.
Tier: Standard | Mode: greenfield | Size: M | Key risk: CAPTCHA at login requires manual fallback.
6 DMAIC phases: Define → Measure (manual baseline) → Analyze (FMEA + selector strategy) → Improve (script build) → Implement (cron + README) → Control (30-day KPI check)._
