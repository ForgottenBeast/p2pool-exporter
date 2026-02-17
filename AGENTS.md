# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

p2pool-exporter is a Python-based Prometheus exporter for monitoring P2Pool mining operations. It collects metrics from P2Pool's API and WebSocket endpoints, tracks miner performance, payouts, exchange rates, and raffle statistics, then exposes them via OpenTelemetry/Prometheus.

## Tech Stack

- **Language**: Python 3.12
- **Build System**: uv (Python package manager)
- **Package Management**: Nix flakes with uv2nix integration
- **Environment**: direnv with Nix
- **Key Dependencies**:
  - aiohttp: Async HTTP client for API calls
  - APScheduler: Job scheduling for periodic scraping
  - Redis: Caching layer for metric state
  - OpenTelemetry: Metrics collection and export (Prometheus + OTLP)
  - Pyroscope: Continuous profiling (dev mode)
  - observlib: Custom telemetry library from https://github.com/ForgottenBeast/observlib

## Development Setup

This project uses Nix flakes for reproducible development environments:

```bash
# Enter development shell (direnv will do this automatically with .envrc)
nix develop

# Install dependencies (handled by Nix, but for manual operations)
uv sync

# Run the exporter (requires environment variables)
uv run p2pool-exporter -a <api-endpoint> -w <wallet1> <wallet2> ...
```

## Key Commands

### Running the Exporter

```bash
# Basic usage with local P2Pool node (recommended)
p2pool-exporter -a http://localhost:3333 -w <wallet-address>

# With all options
p2pool-exporter \
  -a http://localhost:3333 \
  -w <wallet1> <wallet2> \
  -l INFO \
  -t 5 \
  -e EUR USD \
  -P 9093 \
  -d  # Enable dev mode

# Alternative: Using public observer (may have bot protection issues)
# p2pool-exporter -a https://p2pool.observer/mini -w <wallet-address>
```

**Note**: As of Feb 2026, p2pool.observer has implemented bot protection that blocks websocket connections. Using a local P2Pool node is recommended.

### Required Environment Variables

- `OTEL_SERVER`: OpenTelemetry collector endpoint
- `REDIS_SERVER` or `REDIS_DEV_SERVER`: Redis connection (format: `host:port`)
- `PYROSCOPE_SERVER` or `PYROSCOPE_DEV_SERVER`: Pyroscope profiling endpoint (optional, dev mode)

### Code Quality Tools (Available in Nix Shell)

```bash
# Type checking
pyright p2pool-exporter/

# Linting and formatting
ruff check p2pool-exporter/
ruff format p2pool-exporter/

# Security scanning
bandit -r p2pool-exporter/

# Nix code quality
statix check .  # Linter
deadnix .       # Find dead code
vulnix          # Vulnerability scanner
```

### Building

```bash
# Build the package with Nix
nix build

# Build and run
nix run
```

## Architecture

### Core Components

1. **__main__.py**: Application entry point
   - Parses CLI arguments
   - Configures telemetry (OpenTelemetry + Pyroscope)
   - Initializes Redis connection
   - Starts APScheduler for periodic API scraping
   - Launches WebSocket listener for real-time events

2. **api.py**: Data collection logic
   - `collect_api_data()`: Main periodic collection function that gathers:
     - Miner info (last share height)
     - Sideblocks (performance, hashrate estimation)
     - Payouts (rewards tracking)
     - Exchange rates (XMR to fiat)
     - Raffle rates (xmrvsbeast bonus hashrate)
   - `websocket_listener()`: Real-time event processing for:
     - Side blocks (difficulty tracking)
     - Found blocks
     - Orphaned blocks
   - All data is cached in Redis with 1-hour TTL

3. **telemetry.py**: Metrics instrumentation
   - OpenTelemetry meter setup
   - Observable callbacks that read from Redis:
     - `miner_info_callback`: Performance metrics (hashrate, last share)
     - `miner_rewards_callback`: Rewards and payouts
     - `exchange_rate_callback`: Currency exchange rates
   - Factory functions for counters, gauges, histograms
   - URL instrumentor configuration

4. **utils.py**: Utility functions
   - `estimate_hashrate()`: Calculates hashrate from share difficulty over time window

### Data Flow

1. **Periodic Scraping** (configurable interval, default 5 min):
   - APScheduler triggers `collect_api_data()`
   - Async HTTP requests to P2Pool API endpoints
   - Results stored in Redis with `miner:<wallet>` keys
   - Data structure: `{"last_share_height": int, "last_share_timestamp": int, "hashrate": float, "total_blocks": int, "payouts": float, "last_payout_id": str, "raffle_rates": {"hour": float, "day": float}}`

2. **Real-time WebSocket** (continuous):
   - Connects to `/api/events` endpoint
   - Processes stream of block events
   - Updates difficulty and block count metrics immediately

3. **Metrics Export**:
   - OpenTelemetry observable callbacks read from Redis
   - Metrics exposed on configured port (default 9093) via Prometheus exporter
   - Also pushed to OTLP collector if configured

### Metrics Exposed

- `p2pool_exporter_miner_performance`: Gauge (last_share_height, last_share_timestamp, hashrate, raffle_rates_1_hour, raffle_rates_1_day) per miner
- `p2pool_exporter_miner_rewards`: UpDownCounter (total_blocks, payouts) per miner
- `p2pool_exporter_exchange_rate`: Gauge per currency
- `p2pool_exporter_difficulty`: Gauge (main/side pool)
- `p2pool_exporter_blocks`: Counter (sideblock/found/orphaned)
- `p2pool_exporter_ws_event_counter`: WebSocket event count
- `p2pool_exporter_query_counter`: API query counter with status labels
- `p2pool_exporter_latency`: API latency histogram

### Rate Limiting Handling

Exchange rate API (cryptocompare.com) has rate limits. The code checks for:
- Response status codes
- `"RateLimit"` key in response
Errors are logged but don't crash the application.

### State Management

- Redis acts as the single source of truth for current state
- All metrics callbacks read directly from Redis (synchronous client in telemetry.py)
- Async operations use a separate Redis client (in api.py)
- Data expires after 1 hour if not refreshed

### Observability

- All HTTP/async operations are instrumented via OpenTelemetry
- The `@traced` decorator from observlib adds spans and metrics automatically
- Custom label function (`get_query_labels`) adds endpoint and status to metrics
- Dev mode enables:
  - 100% trace sampling (vs 5% in prod)
  - Continuous profiling via Pyroscope
  - Environment attribute tagging

## Nix Integration

The project uses Snowfall Lib for organizing Nix flakes:

- `flake.nix`: Main flake with uv2nix integration
- `nix/packages/p2pool-exporter/`: Package definition
- `nix/shells/dev/`: Development shell with tools
- `nix/uv_setup.nix`: Common UV workspace configuration
- Package overlay handles `observlib` from git with setuptools build fixes

## Important Notes

- The project is in a monorepo structure with the Python package in `p2pool-exporter/` subdirectory
- Uses `observlib` as a git dependency (custom fork from ForgottenBeast)
- Python 3.12 is required and enforced by Nix
- The exporter requires both a working P2Pool API endpoint and Redis instance
- WebSocket connection has auto-reconnect with 5-second backoff on failures
- Last share timestamp has special logic to prevent reset to 0 (api.py:86)
- **API Endpoint**: Use a local P2Pool node (localhost:3333) instead of p2pool.observer to avoid bot protection issues that block websocket connections (see bd-3hu)

<!-- bv-agent-instructions-v1 -->

---

## Beads Workflow Integration

This project uses [beads_viewer](https://github.com/Dicklesworthstone/beads_viewer) for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View issues (launches TUI - avoid in automated sessions)
bv

# CLI commands for agents (use these instead)
br ready              # Show issues ready to work (no blockers)
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br create --title="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once
br sync               # Commit and push changes
```

### Workflow Pattern

1. **Start**: Run `bd ready` to find actionable work
2. **Claim**: Use `bd update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `bd close <id>`
5. **Sync**: Always run `bd sync` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `bd ready` shows only unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers, not words)
- **Types**: task, bug, feature, epic, question, docs
- **Blocking**: `bd dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync                 # Commit beads changes
git commit -m "..."     # Commit code
br sync                 # Commit any new beads changes
git push                # Push to remote
```

### Best Practices

- Check `bd ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `bd create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always `bd sync` before ending session

<!-- end-bv-agent-instructions -->
