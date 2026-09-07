# Project Monitor

An Omarchy desktop app for managing your own Codex accounts, viewing live usage,
and resuming exhausted CLI chats after an account switch.

## Install on Omarchy

Requires Python 3.11+, Codex CLI, and `curl`. Session refresh also requires
Hyprland, `wtype`, and a supported terminal shell. Install the
[Codex CLI](https://learn.chatgpt.com/docs/cli) and make sure `codex --version`
works in your terminal. On Omarchy, missing desktop tools can be installed with
`omarchy pkg add curl wtype`.

```bash
git clone https://github.com/Brenton-vincent-admin/project-monitor.git
cd project-monitor
./install.sh
```

The installer creates a local Python environment, installs PyQt6, and adds
**Project Monitor** to your app launcher. It uses `uv` when available, or Python's
`venv` and `pip`. Keep the cloned directory where you installed it; the launcher
points to it. You can also start the app with `./run.sh`.

Open **Menu → Add account** and enter your own Codex access token, or import a
CSV with `Name,Token` headers. Your accounts are saved locally under
`~/.local/share/project-monitor/`; this repository contains no account tokens.
Use **Refresh usage**, select a ready account, then choose **Switch to Selected**.
Start with **Manual** while setting up. Semi-auto and Full auto refresh eligible
open chats; **Full Access** allows those chats to run commands without sandboxing
or approval prompts.

To update:

```bash
cd project-monitor
git pull --ff-only origin main
./install.sh
```

Close and reopen Project Monitor after updating. Your saved accounts are outside
the clone and remain in place.

## Appearance and account controls

Project Monitor follows the active Omarchy palette, including light and dark
themes. It reads `~/.local/state/omarchy/current/theme/colors.toml` (and the older
config location) every second. Open windows, dialogs, charts and the tray icon
recolor in place; switching themes does not restart the app or affect accounts.
Unreadable or partially replaced theme files retain the last valid palette.
Other desktops use their Qt system palette and font. Status colors are adjusted
for legibility on light and dark backgrounds.

**Menu** contains Import CSV, Add account and Remove selected account.
Selecting a row reveals **Switch to Selected**. Rotation and Full Access remain
on the toolbar.

## Live account usage

**Refresh usage** reads usage and reset information from OpenAI for every saved
account. It also runs on launch and every five minutes. Checks use disposable
Codex profiles, so they do not change the current login or restart chats.

Two small vector charts fit inside each existing row: **5H** on the left and
**7D** on the right. Their arcs show remaining capacity, changing smoothly from
green through amber to red as usage rises. Hover over either chart for its exact
remaining percentage, reset time and last-check age, plus available reset credits.
Missing or stale data is subdued and outlined with dots. The adjacent column
shows the next reported reset. Token IDs are in the account-name tooltip.

- **Ready:** below 80% used across the reported windows.
- **Nearly used up:** at least one window is 80% used or more.
- **Limit reached:** an active quota or workspace credit limit blocks use.
- **Not checked / Stale / Check failed:** availability has not been confirmed.

Snapshots become stale after ten minutes. A passed reset requires another check;
the app does not assume it means a full allowance. Failed checks retain the last
values with a failure label. Workspace credit exhaustion may have no reset time.
Local cooldowns remain in effect until a newer successful usage check supersedes
them. The active account is still labeled **Current**, with its usage state above.

Rotation prefers freshly checked accounts with the most remaining capacity,
then nearly-used-up accounts, then unchecked accounts in the existing rotation
order. Known blocked accounts are skipped. Full auto still requires an exhausted
open chat before switching. Reset credits are displayed, never spent automatically.

Source: [OpenAI account rate limits](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt).

## Three modes

| Mode | What you do | What the app does |
|---|---|---|
| Manual — account only | Click **Rotate account** | Switches account and records the reset time. Does not stop or resume open chats. |
| Semi-auto — switch + refresh | Click **Rotate + refresh exhausted chats** | Switches account and refreshes only exhausted open Codex chats. Healthy chats stay untouched. |
| Full auto — detect + switch + refresh | Select the mode and keep the app running | Checks for exhaustion every five seconds, switches account, and refreshes exhausted chats. Healthy chats stay untouched. |

The mode is remembered. **Switch to Selected** follows the selected mode's refresh
behavior, and does not mark the previous account exhausted. The Full Access option
applies to refreshed chats and is disabled in Manual mode.

Refreshed chats keep their exact conversation IDs and working directories. Closed
conversations are never reopened, and no prompt is automatically submitted. Let the
app finish switching terminal windows before typing. Both refresh modes leave
healthy chats alone.

## Offline behavior and recovery

Before switching, the app checks whether the Codex service is reachable. An offline
or unavailable-service result leaves the login, account records, cooldowns and chats
untouched. Full auto waits and retries when connectivity returns; it does not treat
network failure as quota exhaustion. Manual and Semi-auto display a failure message
and let you retry later.

Account switching and login-status checks run in background workers. Status checks
have a three-second timeout and run every thirty seconds, rather than in the UI's
one-second countdown timer. A failed status check is shown as unavailable. Login
replaces credentials without an explicit logout first.

Full auto returns to Manual for login errors, failed session recovery, or no available
accounts. Resolve the issue and select Full auto again. Offline checks retain Full
auto and retry the pending exhaustion.

## Session detection

The monitor uses the latest structured quota event from each live Codex process,
including credit-depleted events. Closing a terminal, failing to log in, or an old
exhaustion event from a previous process does not count as current exhaustion.
Missing evidence leaves the chat alone in both refresh modes.

Quota lookup scans backwards past large conversation entries with bounded memory
and caches unchanged logs. A large entry cannot hide an earlier exhaustion record.

The desktop restart path supports uniquely identified Hyprland terminal windows
with an interactive Bash, Zsh, Fish, Sh or Dash parent shell. Ambiguous shared windows,
tabs/panes, missing conversation IDs and stale processes are left alone. Failed
restarts show manual recovery commands. A restart is counted only after the same
chat ID appears in a new Codex process on that terminal.
After Codex exits and the original shell returns, the app resets keyboard reporting
before typing the resume command, avoiding garbled input left by the terminated TUI.

## Diagnostics and verification

Logs persist across reboots at `~/.local/state/project-monitor/app.log`, with rotation.
Shutdown stops timers and background workers before closing the database. Late
refresh callbacks are ignored. Unexpected callback errors are logged rather than
allowing PyQt's default exception handling to abort the process.
SIGTERM and Ctrl+C request a clean shutdown, waiting for an in-progress switch
and cancelling usage checks so temporary profiles can be removed. Theme changes
only repaint widgets and never access the account database.

Run `.venv/bin/python -m unittest discover -v` for the automated tests. They cover
all three modes, offline failures, timer responsiveness, automatic retries, and the
closed-database crash regression.

The optional `.venv/bin/python tests/desktop_smoke.py --run` uses disposable Foot
terminals and fake Codex processes to exercise exhausted-only and all-open refresh.
It does not test real account login. Do not run desktop fixtures while another copy
of Project Monitor is in Full auto, since it may discover the fixture processes.
