import pytest
from shortener import encode, decode, min_code_length_for

VALID_CHARS = set("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


class TestEncode:
    def test_zero(self):
        assert encode(0) == "0"

    def test_one(self):
        assert encode(1) == "1"

    def test_base_boundary(self):
        # 62 in base62 is "10" (1*62 + 0)
        assert encode(62) == "10"

    def test_output_uses_valid_chars_only(self):
        for n in [1, 61, 62, 100, 999, 62**4]:
            assert all(c in VALID_CHARS for c in encode(n))

    def test_larger_input_produces_longer_or_equal_output(self):
        assert len(encode(62)) >= len(encode(1))


class TestDecode:
    def test_zero(self):
        assert decode("0") == 0

    def test_one(self):
        assert decode("1") == 1

    def test_known_two_char(self):
        assert decode("10") == 62


class TestRoundtrip:
    @pytest.mark.parametrize("n", [0, 1, 61, 62, 63, 1000, 238327, 62**6 - 1])
    def test_encode_decode_roundtrip(self, n):
        assert decode(encode(n)) == n


class TestMinCodeLength:
    def test_six_chars_covers_56_billion(self):
        assert min_code_length_for(62**6) == 6

    def test_one_char_covers_base(self):
        assert min_code_length_for(62) == 1
