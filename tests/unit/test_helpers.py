"""
Тесты для src/utils/helpers.py

calculate_checksum(data, checksum_index) — XOR всех байт кроме checksum_index
bytes_to_hex(n)                          — int → "0xNN"
"""
import pytest
from src.utils.helpers import bytes_to_hex, calculate_checksum


# ─────────────────────────────────────────────────────────────
# calculate_checksum
# ─────────────────────────────────────────────────────────────

class TestCalculateChecksum:

    def test_empty_data_returns_zero(self):
        assert calculate_checksum(b"") == 0

    def test_single_byte_checksum_is_zero(self):
        # Единственный байт — он же checksum_index, XOR пустого набора = 0
        assert calculate_checksum(b"\xAB") == 0

    def test_two_bytes_xor(self):
        # data=[0xAA, 0xBB], checksum_index=-1 (=1) → XOR байт кроме #1 = 0xAA
        assert calculate_checksum(b"\xAA\xBB") == 0xAA

    def test_three_bytes_xor(self):
        # data=[0x01, 0x02, 0x03], checksum_index=2 → 0x01 ^ 0x02 = 0x03
        assert calculate_checksum(b"\x01\x02\x03") == 0x03

    def test_explicit_middle_index(self):
        # data=[0x10, 0x20, 0x30, 0x40], checksum_index=1
        # XOR байт #0, #2, #3 = 0x10 ^ 0x30 ^ 0x40 = 0x60
        assert calculate_checksum(b"\x10\x20\x30\x40", checksum_index=1) == 0x60

    def test_result_fits_in_byte(self):
        # Много байт — результат всегда в 0..255
        data = bytes(range(256)) + b"\x00"  # checksum_index на последний
        result = calculate_checksum(data)
        assert 0 <= result <= 255

    def test_invalid_index_raises(self):
        with pytest.raises(ValueError):
            calculate_checksum(b"\x01\x02", checksum_index=10)


# ─────────────────────────────────────────────────────────────
# bytes_to_hex
# ─────────────────────────────────────────────────────────────

class TestBytesToHex:

    def test_zero(self):
        assert bytes_to_hex(0) == "0x00"

    def test_single_hex_digit_pads(self):
        # 0xF → должен дать "0x0F", не "0xF"
        assert bytes_to_hex(0xF) == "0x0F"

    def test_one_full_byte(self):
        assert bytes_to_hex(0xFF) == "0xFF"

    def test_two_bytes(self):
        assert bytes_to_hex(0x1234) == "0x1234"

    def test_three_nibbles_pads(self):
        # 0xABC — нечётное число ниблов → должен дополнить до "0x0ABC"
        assert bytes_to_hex(0xABC) == "0x0ABC"

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            bytes_to_hex(-1)
