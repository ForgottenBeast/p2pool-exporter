# p2pool-exporter

Prometheus/OpenTelemetry exporter for P2Pool miners. See `CLAUDE.md` at the
repository root for architecture and development notes.

## Configuration

| Variable | Required | Meaning |
|----------|----------|---------|
| `OTEL_SERVER` | yes | OpenTelemetry collector endpoint |
| `REDIS_SERVER` / `REDIS_DEV_SERVER` | yes | Redis `host:port` (dev variant with `-d`) |
| `REDIS_PASSWORD_FILE` | no | Path to a file containing the Redis password. Trailing newlines are stripped. Intended for systemd `LoadCredential` (`$CREDENTIALS_DIRECTORY/<name>`). Unset means no AUTH. |
| `PYROSCOPE_SERVER` / `PYROSCOPE_DEV_SERVER` | no | Pyroscope profiling endpoint |

The password is only ever read from a file; there is deliberately no
`REDIS_PASSWORD` variable, so the secret never sits in the process
environment.
