# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-10-08

### Added

- Optional Redis authentication: when `REDIS_PASSWORD_FILE` names a file, its
  contents (trailing newlines stripped) are used as the Redis password by both
  the scraper and the telemetry clients. Unset keeps unauthenticated access.
- Tests for the Redis auth configuration (pytest + hypothesis).
