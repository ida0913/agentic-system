# PRD — craigslist-repost-smoke

**Tier:** Standard  **Mode:** greenfield  **Complexity:** M  **Physical:** False

## Overview & Goals

A cron-driven Playwright script that logs into Craigslist every 48 hours and clicks the Renew button on Adi's tutoring listing, refreshing the post timestamp to keep it near the top of local search results. The system runs entirely on Adi's personal MacBook — no servers, no cloud. Success means the listing renews on schedule without any manual action from Adi.

## Problem Statement

Craigslist tutoring listings sink in search ranking as they age; the Renew button only appears after 48 hours and must be clicked manually. Forgetting to click it costs visibility and incoming tutoring inquiries. The current process requires Adi to remember and manually log in every two days, which is error-prone and time-consuming.

## Target Audience

Internal — single operator (Adi)

## Success Metrics

- Listing is renewed within ±5 minutes of every 48-hour eligibility window, verified by log timestamps, for 30 consecutive days without manual intervention.
- Zero missed renewal cycles per calendar month when the laptop is powered on at the scheduled time.

## Features & Requirements

### Functional
- [must] Playwright script reads stored credentials and logs into Craigslist headlessly.
- [must] Navigate to the account's Manage Postings page and locate the tutoring listing.
- [must] Click the Renew button when it is available; exit cleanly and log 'not eligible — skip' when it is not yet eligible.
- [must] Write a timestamped success or failure entry to a local log file after every run.
- [must] macOS cron or launchd job triggers the script every 48 hours.
- [should] Fire a macOS desktop notification (via osascript) on any failure.
- [could] Retry the renewal once after a short delay before recording a final failure.
- [wont] Slack, email, or SMS alerting.

### Non-functional
- Credentials must be stored in macOS Keychain or a secured env file — never hardcoded in source.
- Each script run must complete within 2 minutes.
- Log file must be capped or rotated to stay under 10 MB.

### Usability
- Script is invokable from the terminal with a single command for manual testing.
- Log file uses human-readable timestamped lines (ISO-8601 timestamps, one event per line).
- README documents credential setup, cron configuration, and how to interpret the log.

## User Journey

Trigger: cron/launchd fires every 48 hours → Script reads Craigslist credentials from macOS Keychain or env file → Playwright launches headless Chromium → Navigates to craigslist.org and completes password login → Navigates to My Account › Manage Postings [HANDOFF TO ARCHITECT: confirm exact post-login URL and DOM selectors for the Manage Postings page and the Renew button, including any AJAX-loaded states] → Locates the tutoring listing row → If Renew button is present and clickable, clicks it and waits for the page-state confirmation → Writes timestamped success log entry → Exits with code 0. On any failure (login blocked, button not found, unexpected DOM, network timeout): writes failure log entry with error detail → Fires macOS osascript notification → Exits with non-zero code.

## Assumptions & Constraints

- ASSUMPTION: Craigslist login uses username and password only — no SMS verification, phone call, or interactive CAPTCHA is required during automated headless sessions (Q4 was unanswered). If CAPTCHAs are triggered, full automation is not feasible without a third-party solving service, which is out of scope.
- ASSUMPTION: Craigslist presents a 'Renew' button on the existing listing after 48 hours (timestamp refresh, not delete-and-recreate), based on operator's statement that 'only the post timestamp needs refreshing.'
- ASSUMPTION: Operator's laptop is powered on and not in deep sleep when cron fires. No automatic wake-on-schedule mechanism is in scope.
- Craigslist has no public API; all automation is DOM-based via Playwright/Chromium.
- Craigslist may change its HTML/DOM structure at any time, breaking selectors; the script will require periodic maintenance.
- Automating Craigslist posting may violate their Terms of Service. Operator assumes full legal and ToS risk.
- Python 3.11 and Playwright are already installed on the operator's macOS machine.
- No cloud infrastructure, VPS, or always-on server is used.

## Competitive Context

N/A — internal

## Out of Scope

- Editing listing content (title, body text, price, images) between renewal cycles.
- Full delete-and-recreate posting flow.
- Cloud, VPS, or server deployment.
- Slack, email, or SMS notifications.
- Multi-listing or multi-account support.
- CAPTCHA solving or human-in-the-loop verification steps.
- Windows or Linux OS support.
- Automatic laptop wake scheduling.

## Acceptance Criteria

1. When the script runs and the listing is eligible for renewal, the renewal completes and a timestamped success entry appears in the log file within 2 minutes — verifiable by inspecting the log.
2. When the script runs and the listing is not yet eligible (< 48 hours old), the script exits with code 0 and logs 'not eligible — skip' with no notification fired.
3. When credentials are invalid or login fails, the script exits with a non-zero code, a failure entry appears in the log, and a macOS desktop notification appears.
4. Running 'crontab -l' or 'launchctl list' on the operator's machine shows the 48-hour schedule entry pointing to the script.
5. No Craigslist credentials appear in plaintext in any source file, confirmed by grep of the project directory.

## DMAIC Plan

### Define
**Owner:** PM  **Entry:** Operator has submitted the original request and answered clarifying questions.  **Exit:** PRD is complete and operator has acknowledged the scope, assumptions, and out-of-scope items.

- PRD with acceptance criteria
- SIPOC diagram
- CTQ tree
- Project classification (tier/mode/complexity)

### Measure
**Owner:** PM  **Entry:** PRD approved and scope confirmed by operator.  **Exit:** Manual baseline cost (time/month, missed renewals/month) is documented and agreed as the benchmark the automation must beat.

- Manual baseline documented: estimated time per manual renewal (approx. 3–5 min login + navigate + click) multiplied by renewal frequency (every 48 h = ~15×/month) = ~45–75 min/month of pure manual toil.
- Observed frequency of missed renewals per month and resulting listing-age degradation (days listing goes stale).
- Baseline inquiry/contact volume correlated with listing freshness, if Adi has historical data.

### Analyze
**Owner:** Architect  **Entry:** Manual baseline documented.  **Exit:** Architect confirms selectors are stable, login flow is fully mappable headlessly, and a written technical design is approved by operator.

- Craigslist Manage Postings page URL and DOM selector map for the Renew button (confirmed via live browser inspection).
- Login flow analysis: form fields, redirect sequence, session cookie lifetime, headless vs. headed behavior.
- Enumerated failure modes: CAPTCHA trigger, session expiry, listing not found, DOM change, network timeout.
- macOS cron vs. launchd tradeoff recommendation (sleep behavior, logging, reliability).
- Credential storage approach decision: macOS Keychain via keyring library vs. .env file with restricted permissions.

### Improve
**Owner:** Engineer  **Entry:** Technical design approved by Architect.  **Exit:** Script passes a live end-to-end smoke test on Adi's actual Craigslist tutoring listing and all five acceptance criteria are satisfied.

- Python 3.11 Playwright script: login, Manage Postings navigation, eligibility check, Renew click, page-state confirmation.
- macOS osascript notification hook on failure.
- Optional single retry on transient network or timeout errors.
- Credential loader module (Keychain via keyring or env file).
- Log writer with rotation/cap at 10 MB.
- Smoke test runnable from terminal against a real listing.

### Implement
**Owner:** Engineer  **Entry:** Script tested and all acceptance criteria pass.  **Exit:** First automated 48-hour renewal fires without manual intervention and is recorded in the log.

- cron or launchd job installed on operator's MacBook with the 48-hour schedule.
- Credentials stored in macOS Keychain (not in source files).
- Log file path confirmed and writable.
- First automated renewal cycle observed and log entry verified by operator.

### Control
**Owner:** PM  **Entry:** First automated renewal confirmed in log.  **Exit:** 30 consecutive days of on-schedule renewals with zero missed cycles (when laptop is on) and operator holds the maintenance runbook.

- Log review checklist: weekly scan for consecutive failures or 'not eligible' anomalies.
- Selector maintenance runbook: steps to re-map DOM selectors when Craigslist changes its markup.
- 30-day clean-run verification report confirming zero missed cycles (when laptop was on).
- Escalation procedure if CAPTCHA is consistently encountered (options: switch to headed mode, manual fallback, CAPTCHA service decision).

---

_Craigslist Tutoring Listing Auto-Renewer: Playwright + cron script that logs in and clicks Renew every 48 hours on macOS, with local file logging and desktop failure notifications.
Tier: Standard | Mode: greenfield | Size: M
6 DMAIC phases: Define → Measure → Analyze → Improve → Implement → Control_
