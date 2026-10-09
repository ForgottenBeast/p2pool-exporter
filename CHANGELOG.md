# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.1] - 2026-10-09

### Fixed

- `get_payouts()` logged the full payout record at INFO level, including the
  P2Pool API's `coinbase_private_key` field, writing it to the system journal
  in cleartext. All logging of externally-sourced payloads (payouts, exchange
  rate error responses) now passes through a recursive redaction helper that
  replaces the value of any key matching `key`, `secret`, `password`, or
  `token` (case-insensitive) with `<redacted>` before it reaches the logger.
- Added property-based tests (pytest + hypothesis) asserting no sensitive
  value survives redaction for arbitrary nested dict/list payloads.

## [1.4.0] - 2026-10-08

### Added

- Optional Redis authentication: when `REDIS_PASSWORD_FILE` names a file, its
  contents (trailing newlines stripped) are used as the Redis password by both
  the scraper and the telemetry clients. Unset keeps unauthenticated access.
- Tests for the Redis auth configuration (pytest + hypothesis).
