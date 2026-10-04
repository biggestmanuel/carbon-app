"""TOTP itself, checked against the RFC test vectors.

If the arithmetic is wrong the failure mode is silent: codes simply never match,
or worse, match for the wrong reason. So the published RFC 6238 vectors are the
test, not a round trip through the module's own code.

RFC 6238 appendix B uses an 8-byte ASCII seed ("12345678901234567890") and gives
SHA-1 values for 8 digits at six timestamps. The module produces 6 digits by
default, so these tests ask for 8 explicitly where they compare against the RFC.
"""

import base64
import time

import pytest

from totp import (
    DIGITS,
    MIN_SECRET_BYTES,
    PERIOD,
    WINDOW,
    code_at,
    counter_for_code,
    current_code,
    current_counter,
    decode_secret,
    generate_secret,
    normalise_secret,
    provisioning_uri,
    verify,
)

# RFC 6238 appendix B states the seed as raw ASCII bytes. The module's interface
# is base32, so the seed is encoded here once and every test below goes through
# the same decode path a real secret takes. That way the vectors also exercise
# the decoding, rather than being handed raw key bytes through a back door.
RFC_SEED_BYTES = b"12345678901234567890"
RFC_SECRET = base64.b32encode(RFC_SEED_BYTES).decode("ascii")


def _secret():
    return RFC_SECRET


def test_the_rfc_seed_survives_the_base32_round_trip():
    # Guards the fixture itself: if this drifts, every vector test below would be
    # comparing against the wrong key.
    assert decode_secret(RFC_SECRET) == RFC_SEED_BYTES
    assert decode_secret(normalise_secret(RFC_SECRET)) == RFC_SEED_BYTES


# RFC 6238 appendix B, SHA-1 row.
RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


@pytest.mark.parametrize("timestamp,expected", RFC_VECTORS)
def test_it_matches_the_rfc_6238_vectors(timestamp, expected):
    counter = timestamp // PERIOD
    assert code_at(_secret(), counter, digits=8) == expected


def test_the_counter_is_derived_from_the_period():
    # 59 seconds is inside the first 30s step; 60 starts the second.
    assert current_counter(59) == 1
    assert current_counter(60) == 2
    assert current_counter(89) == 2
    assert current_counter(90) == 3


def test_codes_are_six_digits_and_zero_padded():
    # A code shorter than six digits would be accepted by some clients and
    # rejected by others, and 000001 must not become 1.
    code = current_code(_secret(), 1234567890)
    assert len(code) == DIGITS
    assert code == "005924"
    assert code.isdigit()


def test_a_code_verifies_inside_its_own_window():
    secret = _secret()
    code = code_at(secret, current_counter(1000))
    assert verify(secret, code, now=1000) is True


def test_the_window_tolerates_exactly_one_step_of_drift():
    secret = _secret()
    now = 1000
    counter = current_counter(now)

    # The previous step's code still works: a phone's clock can be behind.
    assert verify(secret, code_at(secret, counter - 1), now=now) is True
    # And the next one's, for a clock running fast.
    assert verify(secret, code_at(secret, counter + 1), now=now) is True
    # Two steps is 60 seconds away, and that is a refused clock, not drift.
    assert verify(secret, code_at(secret, counter - 2), now=now) is False
    assert verify(secret, code_at(secret, counter + 2), now=now) is False


def test_the_window_is_narrow_by_design():
    # Wider tolerances multiply the number of live codes. One step either side is
    # 90 seconds of validity, which is what every authenticator app assumes.
    assert WINDOW == 1


class TestRejectsMalformedCodes:
    @pytest.mark.parametrize("code", [
        "", "12345", "1234567", "abcdef", "12345a", " 123456", "123456 ",
        "12345\n", "00000a", None, 123456, ["123456"],
    ])
    def test_anything_that_is_not_six_digits_is_refused(self, code):
        # Rejected before any HMAC work, and without raising on the wrong type.
        assert verify(_secret(), code, now=1000) is False

    def test_a_zero_padded_code_is_not_matched_by_its_short_form(self):
        secret = _secret()
        assert verify(secret, "005924", now=1234567890) is True
        # The same digits without the leading zero must not satisfy it.
        assert verify(secret, "5924", now=1234567890) is False

    def test_an_empty_secret_never_verifies(self):
        assert verify("", "123456", now=1000) is False
        assert verify(None, "123456", now=1000) is False


class TestSecrets:
    def test_a_generated_secret_is_usable(self):
        secret = generate_secret()
        assert code_at(secret, 1) is not None
        assert verify(secret, current_code(secret), now=time.time()) is True

    def test_generated_secrets_differ(self):
        assert len({generate_secret() for _ in range(50)}) == 50

    def test_a_secret_has_the_expected_entropy_length(self):
        # 20 bytes is the RFC 4226 recommendation, and comes out as 32 base32
        # characters, which is what authenticator apps display.
        secret = generate_secret()
        assert len(secret) == 32
        assert len(decode_secret(secret)) == 20

    def test_a_generated_secret_has_no_padding(self):
        # Some authenticator apps mishandle the trailing '='.
        assert not generate_secret().endswith("=")

    @pytest.mark.parametrize("secret", [
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        "gezdgnbvgy3tqojqgezdgnbvgy3tqojq",
        "GEZD GNBV GY3T QOJQ GEZD GNBV GY3T QOJQ",
        "gezd-gnbv-gy3t-qojq-gezd-gnbv-gy3t-qojq",
        "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ====",
    ])
    def test_a_human_copied_secret_still_verifies(self, secret):
        # Users paste these in groups of four, in either case, and some add
        # dashes. Rejecting a correctly-pasted secret at enrolment is a support
        # call and a locked-out account.
        expected = current_code(_secret())
        assert verify(_secret(), expected) is True
        assert decode_secret(secret) == decode_secret(_secret())

    def test_padding_is_restored_when_decoding(self):
        # A secret pasted without its trailing '=' is the common case: base32
        # decoding rejects a length that is not a multiple of eight, so
        # normalise_secret has to put the padding back.
        assert decode_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ") is not None
        # 8 characters is already a whole number of base32 blocks.
        assert normalise_secret("abcd efgh") == "ABCDEFGH"
        # 4 characters needs 4 '=' to reach a multiple of 8.
        assert normalise_secret("abcd") == "ABCD===="
        assert decode_secret("abcd") == decode_secret("ABCD====")

    @pytest.mark.parametrize("secret", ["not-base32!", "1", "!!!!!", "!!!!!!!!"])
    def test_an_invalid_secret_decodes_to_none(self, secret):
        assert decode_secret(secret) is None

    @pytest.mark.parametrize("secret", ["", None, "   "])
    def test_an_absent_secret_decodes_to_none(self, secret):
        # None rather than b"": callers treat both as "cannot verify", and an
        # empty byte string would be a truthy-looking key at the call site.
        assert decode_secret(secret) is None

    def test_a_short_secret_is_refused_even_though_it_decodes(self):
        # Four base32 characters is 20 bits and verifies codes perfectly well,
        # which is the problem: it is trivially brute-forceable. A weak seed must
        # not be able to pass just because it is well-formed.
        assert decode_secret("ABCD") is None
        assert decode_secret("ABCDEFGH") is None  # 40 bits
        assert decode_secret(RFC_SECRET) is not None  # 160 bits

    def test_a_generated_secret_always_meets_the_floor(self):
        for _ in range(20):
            key = decode_secret(generate_secret())
            assert key is not None
            assert len(key) >= MIN_SECRET_BYTES

    def test_code_at_returns_none_for_an_invalid_secret(self):
        # Rather than raising: a corrupted row should refuse a login, not 500.
        assert code_at("!!!not-base32!!!", 1) is None


class TestCounterForCode:
    def test_it_reports_the_matched_step(self):
        secret = _secret()
        now = 1000
        counter = current_counter(now)
        code = code_at(secret, counter - 1)
        assert counter_for_code(secret, code, now=now) == counter - 1

    def test_it_returns_none_for_a_wrong_code(self):
        assert counter_for_code(_secret(), "000000", now=1000) is None

    def test_it_returns_none_outside_the_window(self):
        secret = _secret()
        now = 1000
        assert counter_for_code(secret, code_at(secret, current_counter(now) - 5), now=now) is None


class TestProvisioningUri:
    def test_it_carries_everything_an_app_needs(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        uri = provisioning_uri(secret, "alice", issuer="carbon-app")

        assert uri.startswith("otpauth://totp/")
        assert "secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ" in uri
        assert "issuer=carbon-app" in uri
        assert "algorithm=SHA1" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_the_issuer_is_in_the_label(self):
        # Without it, an app shows the bare account name and a user with several
        # services cannot tell the entries apart.
        uri = provisioning_uri("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "alice", issuer="carbon-app")
        assert "carbon-app%3Aalice" in uri

    def test_the_username_is_escaped(self):
        # A username cannot contain ':' or '/', but issuer is operator-supplied
        # and a '#' in it would truncate the URI at the fragment.
        uri = provisioning_uri("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "alice", issuer="a#b")
        assert "%23" in uri

    def test_it_carries_no_padding_in_the_secret(self):
        # Trailing '=' in a query parameter is a frequent source of
        # authenticator-app import failures.
        uri = provisioning_uri("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ====", "alice")
        assert "secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&" in uri
        assert "=" not in uri.split("secret=")[1].split("&")[0]

    def test_it_returns_none_without_a_secret_or_username(self):
        assert provisioning_uri("", "alice") is None
        assert provisioning_uri("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "") is None


def test_the_module_imports_nothing_third_party():
    # TOTP is three stdlib modules of arithmetic. If this ever starts importing
    # a TOTP package, the "no dependency needed" property has been broken.
    import pathlib

    import totp

    source = pathlib.Path(totp.__file__).read_text(encoding="utf-8")
    for forbidden in ("import pyotp", "import requests", "import cryptography"):
        assert forbidden not in source
