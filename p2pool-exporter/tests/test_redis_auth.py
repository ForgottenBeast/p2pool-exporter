import string

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from p2pool_exporter import api, telemetry
from p2pool_exporter.utils import redis_auth_kwargs

# Redis passwords as an operator would store them: printable, no surrounding
# whitespace (the trailing newline is what `echo`/agenix files add).
passwords = st.text(
    alphabet=string.ascii_letters + string.digits + string.punctuation,
    min_size=1,
    max_size=64,
)


class RecordingRedis:
    calls = []

    def __init__(self, *args, **kwargs):
        RecordingRedis.calls.append(kwargs)


@pytest.fixture(autouse=True)
def no_password_env(monkeypatch):
    monkeypatch.delenv("REDIS_PASSWORD_FILE", raising=False)


@given(password=passwords, newline=st.sampled_from(["", "\n", "\r\n"]))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_password_file_read_and_trailing_newline_stripped(
    tmp_path, monkeypatch, password, newline
):
    secret = tmp_path / "redis-password"
    secret.write_text(password + newline)
    monkeypatch.setenv("REDIS_PASSWORD_FILE", str(secret))

    assert redis_auth_kwargs() == {"password": password}


def test_absent_config_means_no_password_kwarg():
    assert redis_auth_kwargs() == {}


@pytest.mark.parametrize(
    "configure",
    [
        lambda: api.configure_redis("localhost", "6379"),
        lambda: telemetry.initialize_telemetry("localhost", "6379", [], []),
    ],
    ids=["api", "telemetry"],
)
@pytest.mark.parametrize("with_password", [True, False])
def test_clients_receive_password_only_when_configured(
    tmp_path, monkeypatch, configure, with_password
):
    RecordingRedis.calls = []
    monkeypatch.setattr(api.redis, "Redis", RecordingRedis)
    monkeypatch.setattr(telemetry.redis, "Redis", RecordingRedis)
    if with_password:
        secret = tmp_path / "redis-password"
        secret.write_text("s3cret\n")
        monkeypatch.setenv("REDIS_PASSWORD_FILE", str(secret))

    configure()

    (kwargs,) = RecordingRedis.calls
    assert kwargs["host"] == "localhost"
    if with_password:
        assert kwargs["password"] == "s3cret"
    else:
        assert "password" not in kwargs
