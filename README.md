# System Health Monitor

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat&logo=python&logoColor=white)
[![CI](https://github.com/mojtaba-py-code/system-health-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/mojtaba-py-code/system-health-monitor/actions/workflows/ci.yml)
![Tests](https://img.shields.io/badge/tests-83%20passing-brightgreen?style=flat)
![Coverage](https://img.shields.io/badge/coverage-90%25-brightgreen?style=flat)
![Lint](https://img.shields.io/badge/ruff-clean-brightgreen?style=flat)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat)

A **production-grade, cross-platform system monitoring tool** built in Python. It collects CPU,
memory, disk, network, process, service, temperature, battery and uptime metrics **concurrently**,
evaluates them against configurable thresholds, raises alerts, stores history in SQLite, and renders
a live colour-coded dashboard — a lightweight take on enterprise monitoring tools.

Designed to be **secure, modular and low-overhead**: metrics are gathered in parallel with a thread
pool, the only privileged action (process control) is guarded behind validation and confirmation, and
sensitive data is redacted before it is ever logged.

---

## ✨ Features

| Subsystem | Highlights |
|-----------|------------|
| **CPU** | Overall & per-core usage, frequency, load-per-core, context switches |
| **Memory** | RAM & swap usage, cached/buffers, threshold alerts |
| **Disk** | Per-partition usage, free space, live read/write throughput |
| **Network** | Upload/download rate, interfaces, IPs, connections, listening ports |
| **Process** | Hottest processes (CPU/RAM, normalised), zombies, safe kill/suspend/resume |
| **Service** | Windows Services & Linux systemd watch-list health |
| **Temperature** | CPU/sensor temperatures with overheating alerts (where exposed) |
| **Battery** | Level, charging status, time remaining |
| **Uptime** | Boot time and elapsed uptime |
| **Filesystem** | Real-time create/modify/delete/move events on watched folders |

**Platform features**

- ⚡ **Concurrent collection** via `ThreadPoolExecutor` (fast, low CPU overhead)
- 🎨 **Live rich dashboard** with colour-coded status per subsystem
- 🔔 **Alert system** — console, log file, webhook (HTTPS) & desktop, with per-metric cooldown
- 🗄️ **SQLite history** of metrics and alerts, with automatic retention pruning
- 📄 **Reports** in JSON / CSV / TXT / HTML (PDF optional)
- ⚙️ **YAML configuration** for intervals, thresholds, alert channels and more
- 📝 **Separate rotating logs** for monitoring, errors and alerts

---

## 🏗️ Architecture

```
system_health_monitor/
├── main.py                    # argparse CLI: monitor, dashboard, report, ...
│
├── config/
│   ├── settings.yaml          # intervals, logging, alerts, paths, enabled monitors
│   ├── thresholds.yaml        # per-subsystem warning/critical values
│   └── logging.yaml           # optional declarative logging config
│
├── core/
│   ├── base.py                # Metric / Severity / Threshold / Monitor (ABC)
│   ├── cpu_monitor.py  memory_monitor.py  disk_monitor.py  network_monitor.py
│   ├── process_monitor.py  service_monitor.py  temperature_monitor.py
│   ├── battery_monitor.py  uptime_monitor.py
│   ├── filesystem_monitor.py  # real-time folder watch (watchdog)
│   ├── collector.py           # concurrent orchestration → HealthSnapshot
│   ├── alert_manager.py       # threshold breaches → dispatched, de-duped alerts
│   ├── report_generator.py    # JSON / CSV / TXT / HTML / PDF
│   ├── dashboard.py           # rich live dashboard
│   └── scheduler.py           # periodic collection loop
│
├── utils/
│   ├── config.py              # layered defaults + YAML merge
│   ├── security.py            # path/input validation, safe subprocess, redaction
│   ├── logging_config.py      # rotating monitoring/errors/alerts logs
│   ├── formatting.py          # human sizes, rates, durations
│   └── exceptions.py          # typed error hierarchy
│
├── database/metrics_db.py     # SQLite metrics + alert history
├── tests/                     # 83 tests · 90% coverage
├── logs/  reports/
├── .github/workflows/ci.yml   # lint · cross-platform tests · security scans
└── pyproject.toml  requirements.txt  SECURITY.md  README.md
```

**Data flow:** `Collector` runs every enabled `Monitor` concurrently → each returns a `MonitorResult`
of `Metric`s (severity derived from `Threshold`s) → aggregated into a `HealthSnapshot` → consumed by
the dashboard, alert manager, database and report generator.

---

## 🚀 Installation

```bash
git clone https://github.com/mojtaba-py-code/system-health-monitor.git
cd system-health-monitor

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate

pip install -r requirements.txt
```

Requires **Python 3.12+**.

---

## 💻 Usage

```bash
python main.py --help                # list commands
python main.py <command> --help      # per-command help
```

### Examples

```bash
# Live auto-refreshing dashboard (Ctrl-C to stop)
python main.py dashboard --interval 2

# Continuous monitoring with alerts, storing history
python main.py monitor --interval 5

# Run a fixed number of cycles then exit
python main.py monitor --cycles 10 --interval 1

# One-off health report
python main.py report --html -o reports/
python main.py report --json

# Query stored history
python main.py history --subsystem cpu --limit 20
python main.py history --summary

# Alerts: recent history, or evaluate right now
python main.py alerts
python main.py alerts --now

# Processes: view hottest, inspect or (carefully) control one
python main.py processes --top 10
python main.py processes --details 4321
python main.py processes --kill 4321          # asks for confirmation
python main.py processes --kill 4321 --force  # scripted

# Watch critical services
python main.py services --watch Dhcp Dnscache      # Windows
python main.py services --watch sshd nginx docker  # Linux

# Watch folders for changes in real time (Ctrl-C to stop)
python main.py watch C:/important D:/data
python main.py watch /etc --duration 30 --no-recursive

# Show the effective configuration
python main.py config
```

**Global flags:** `--config`, `--thresholds`, `--interval`, `--output`, `--json/--csv/--html/--pdf`,
`--verbose`, `--quiet`.

---

## ⚙️ Configuration

Behaviour is controlled by `config/settings.yaml`; alert thresholds by `config/thresholds.yaml`.
Anything omitted falls back to a safe built-in default.

```yaml
# thresholds.yaml — higher is worse by default; set higher_is_worse: false for
# "free" resources (disk free %, battery %).
cpu:
  usage_percent: { warning: 80, critical: 95 }
disk:
  free_percent:  { warning: 20, critical: 8, higher_is_worse: false }
```

---

## 🔒 Security

Although the tool is read-mostly, security is treated as a first-class concern:

- **Input validation** — intervals, PIDs and paths are validated before use.
- **Safe subprocess** — service queries run without a shell, only from an **allow-list** of
  executables, with a timeout (no shell-injection, no hangs).
- **Guarded process control** — kill/suspend/resume validate the PID, refuse protected PIDs (0/1) and
  the monitor's own process, and require explicit confirmation or `--force`.
- **Path sanitisation** — report/database writes are resolved and can be confined to allow-listed
  roots; writing through a symlink is refused.
- **Secret redaction** — command lines are scrubbed of `password=`/`token=`-style secrets before
  logging or exporting.
- **Webhook hardening** — alert webhooks are only sent to **HTTPS** endpoints.
- **Least exposure** — the tool reports aggregate health, not unnecessary sensitive system detail.

---

## 🧪 Testing

```bash
pip install -r requirements-dev.txt
pytest --cov=core --cov=utils --cov=database --cov=main --cov-report=term-missing
ruff check .
```

**83 tests, 90% coverage, ruff-clean.** Hardware-dependent paths (sensors, swap, load average,
services) are covered with monkeypatched fixtures so the suite is deterministic and cross-platform.

---

## 📄 License

Released under the [MIT License](LICENSE).
