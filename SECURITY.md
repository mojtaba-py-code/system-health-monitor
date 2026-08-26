# Security Policy

## Reporting a vulnerability

Please report security issues privately through GitHub's
[private vulnerability reporting](https://github.com/mojtaba-py-code/system-health-monitor/security/advisories/new)
rather than opening a public issue.

Include the version or commit, the platform, and the steps to reproduce. I aim
to acknowledge a report within 72 hours and to ship a fix or a mitigation plan
within 30 days.

## Scope

The monitor is read-mostly, but it touches the filesystem, spawns a small set of
system commands and can terminate processes. The controls below are the ones
worth attacking — a bypass of any of them is a valid report.

| Control | Where | Guarantee |
|---------|-------|-----------|
| Command allow-list | `utils/security.py` → `safe_run` | Only a fixed set of executables may run, never through a shell, always with a timeout |
| PID validation | `utils/security.py` → `validate_pid` | Kill/suspend/resume refuse PID 0 and 1 and non-integer input |
| Output path confinement | `utils/security.py` → `validate_output_path` | Report and database writes resolve `..`, refuse symlinks, and stay inside `security.allowed_output_roots` when it is set |
| Interval validation | `utils/security.py` → `validate_interval` | Polling intervals are bounded to a sane range |
| Secret redaction | `utils/security.py` → `redact` | `password=`/`token=`-style values are scrubbed from command lines before they reach a log, a report or an alert |
| Webhook transport | `core/alert_manager.py` → `_webhook` | Alerts are sent to HTTPS endpoints only; anything else is refused and logged |
| SQL parameterisation | `database/metrics_db.py` | Every query binds values as parameters — no string interpolation |

## Out of scope

- Running the tool as root/Administrator and then terminating a system process:
  the allow-list and PID guards are not a substitute for OS permissions.
- Metrics the operating system exposes to any unprivileged user.
- Findings that require an attacker to already control `config/settings.yaml`,
  which is trusted input equivalent to the code itself.

## Configuration notes

- `config/settings.yaml` ships with `webhook_url: ""` and no watched paths.
  Anything you add there is yours; do not commit a real webhook URL — keep it in
  `config/secrets.yaml` or a `*.local.yaml` override, both of which are ignored
  by git.
- `security.allowed_output_roots` is empty by default, which means writes are
  resolved but not confined. Set it when running the monitor somewhere the
  output path could be attacker-influenced.
- `security.redact_secrets` is on by default. Turning it off will put process
  command lines into logs verbatim.

## Supported versions

The latest commit on `main` is the supported version.
