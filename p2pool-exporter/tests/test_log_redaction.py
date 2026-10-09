import json
import string

import pytest
from hypothesis import assume, given, settings, strategies as st

from p2pool_exporter.utils import redact_sensitive

SENSITIVE_KEYS = [
    "private_key",
    "coinbase_private_key",
    "secret",
    "api_secret",
    "password",
    "redis_password",
    "token",
    "auth_token",
    "key",
]

# Letters-only and long enough that it can never coincide with the string
# form of an unrelated numeric/boolean field value drawn alongside it.
secret_values = st.text(
    alphabet=string.ascii_letters,
    min_size=12,
    max_size=64,
)

safe_values = st.one_of(
    st.text(max_size=32),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)

# Fixed pool of key names, deliberately free of any sensitive-marker
# substring, used as the "ordinary field" half of each payload.
safe_keys = st.sampled_from(
    ["miner", "amount", "timestamp", "id", "status", "note", "label", "wallet"]
)


@given(
    sensitive_key=st.sampled_from(SENSITIVE_KEYS),
    secret_value=secret_values,
    other_key=safe_keys,
    other_value=safe_values,
)
@settings(max_examples=100)
def test_sensitive_top_level_value_is_redacted(
    sensitive_key, secret_value, other_key, other_value
):
    # The unrelated field may coincidentally equal the secret string; that
    # would make the "secret absent from output" check meaningless, not
    # exercise a redaction bug, so skip that coincidence.
    assume(str(other_value) != secret_value)
    payload = {sensitive_key: secret_value, other_key: other_value}
    redacted = redact_sensitive(payload)

    assert redacted[sensitive_key] == "<redacted>"
    assert redacted[other_key] == other_value
    # The formatted output (what actually lands in the log) must never
    # contain the raw secret value.
    assert secret_value not in json.dumps(redacted)


@given(
    sensitive_key=st.sampled_from(SENSITIVE_KEYS),
    secret_value=secret_values,
    wrapper_key=safe_keys,
)
@settings(max_examples=100)
def test_sensitive_nested_dict_value_is_redacted(
    sensitive_key, secret_value, wrapper_key
):
    payload = {wrapper_key: {sensitive_key: secret_value, "amount": 1.5}}
    redacted = redact_sensitive(payload)

    assert redacted[wrapper_key][sensitive_key] == "<redacted>"
    assert redacted[wrapper_key]["amount"] == 1.5
    assert secret_value not in json.dumps(redacted)


@given(
    sensitive_key=st.sampled_from(SENSITIVE_KEYS),
    secret_value=secret_values,
)
@settings(max_examples=100)
def test_sensitive_value_inside_list_of_dicts_is_redacted(sensitive_key, secret_value):
    payload = {"items": [{sensitive_key: secret_value, "id": 1}]}
    redacted = redact_sensitive(payload)

    assert redacted["items"][0][sensitive_key] == "<redacted>"
    assert redacted["items"][0]["id"] == 1
    assert secret_value not in json.dumps(redacted)


def test_real_payout_shape_hides_private_key():
    payload = {
        "payout": {
            "miner": "4Axxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "payout_id": "abc123",
            "amount": 0.1234,
            "private_key": "7f9a6cb2e4a1facadeb00c0ffeedeadbeef00112233445566778899aabbccdd",
            "timestamp": 1760000000,
        }
    }

    redacted = redact_sensitive(payload)

    assert redacted["payout"]["private_key"] == "<redacted>"
    assert redacted["payout"]["miner"] == payload["payout"]["miner"]
    assert redacted["payout"]["amount"] == 0.1234
    assert (
        "7f9a6cb2e4a1facadeb00c0ffeedeadbeef00112233445566778899aabbccdd"
        not in json.dumps(redacted)
    )


def test_does_not_mutate_input():
    payload = {"private_key": "shhh"}
    redact_sensitive(payload)
    assert payload["private_key"] == "shhh"


@pytest.mark.parametrize(
    "value",
    ["a string", 42, 3.14, True, None, ["a", "b"]],
)
def test_non_dict_values_pass_through_unchanged(value):
    assert redact_sensitive(value) == value
