"""
Тесты протокола STM32 UART.

Покрывают:
  uart_stm32_init.py — calc_checksum, build_packet, parse_packet
  uart_stm32_rx.py   — decode_type, decode_error_packet

Структура пакета: [0xBF | TYPE | LEN | DATA... | CRC | 0xFF]
CRC = (TYPE + LEN + sum(DATA)) % 256
"""
import pytest

from src.interfaces.uart_stm32_init import (
    ACK_TYPE,
    BYTE_END,
    BYTE_START,
    NACK_TYPE,
    STM32PacketError,
    build_packet,
    calc_checksum,
    parse_packet,
)
from src.interfaces.uart_stm32_rx import (
    SYS_PART_DHT22,
    SYS_PART_HALL,
    SYS_PART_VOLTAGE,
    decode_error_packet,
    decode_type,
)


# ─────────────────────────────────────────────────────────────
# calc_checksum
# ─────────────────────────────────────────────────────────────

class TestCalcChecksum:

    def test_empty_data(self):
        # CRC = TYPE + 0 + 0 = TYPE
        assert calc_checksum(0x05, b"") == 0x05

    def test_single_data_byte(self):
        # CRC = (0x05 + 1 + 0x01) % 256 = 7
        assert calc_checksum(0x05, b"\x01") == 7

    def test_wraps_at_256(self):
        # Проверяем что % 256 работает
        result = calc_checksum(0xFF, bytes([0xFF]))
        assert result == (0xFF + 1 + 0xFF) % 256
        assert 0 <= result <= 255

    def test_multiple_bytes(self):
        data = b"\x01\x02\x03"
        expected = (0x09 + 3 + 1 + 2 + 3) % 256
        assert calc_checksum(0x09, data) == expected


# ─────────────────────────────────────────────────────────────
# build_packet
# ─────────────────────────────────────────────────────────────

class TestBuildPacket:

    def test_markers_present(self):
        pkt = build_packet(0x05, b"\x01")
        assert pkt[0] == BYTE_START   # 0xBF
        assert pkt[-1] == BYTE_END    # 0xFF

    def test_type_and_len_fields(self):
        pkt = build_packet(0x09, b"\xAA\xBB")
        assert pkt[1] == 0x09   # TYPE
        assert pkt[2] == 2      # LEN

    def test_empty_data_length(self):
        # BYTE_START + TYPE + LEN + CRC + BYTE_END = 5 байт
        pkt = build_packet(0x09, b"")
        assert len(pkt) == 5
        assert pkt[2] == 0      # LEN = 0

    def test_crc_matches_calc(self):
        data = b"\x03"
        pkt = build_packet(0x05, data)
        crc_in_packet = pkt[-2]
        assert crc_in_packet == calc_checksum(0x05, data)

    def test_data_too_long_raises(self):
        with pytest.raises(ValueError):
            build_packet(0x05, bytes(101))  # MAX_DATA_LEN = 100

    def test_ack_packet_no_data(self):
        pkt = build_packet(ACK_TYPE, b"")
        assert pkt[1] == ACK_TYPE
        assert pkt[2] == 0


# ─────────────────────────────────────────────────────────────
# parse_packet
# ─────────────────────────────────────────────────────────────

class TestParsePacket:

    def test_roundtrip_with_data(self):
        t, d = parse_packet(build_packet(0x09, b"\x01\x02\x03"))
        assert t == 0x09
        assert d == b"\x01\x02\x03"

    def test_roundtrip_empty_data(self):
        t, d = parse_packet(build_packet(ACK_TYPE, b""))
        assert t == ACK_TYPE
        assert d == b""

    def test_too_short_raises(self):
        with pytest.raises(STM32PacketError, match="короткий"):
            parse_packet(b"\xBF\x05")

    def test_bad_start_marker_raises(self):
        pkt = bytearray(build_packet(0x05, b"\x01"))
        pkt[0] = 0x00
        with pytest.raises(STM32PacketError, match="BYTE_START"):
            parse_packet(bytes(pkt))

    def test_bad_end_marker_raises(self):
        pkt = bytearray(build_packet(0x05, b"\x01"))
        pkt[-1] = 0x00
        with pytest.raises(STM32PacketError, match="BYTE_END"):
            parse_packet(bytes(pkt))

    def test_corrupted_crc_raises(self):
        pkt = bytearray(build_packet(0x05, b"\x01"))
        pkt[-2] ^= 0xFF  # портим контрольную сумму
        with pytest.raises(STM32PacketError, match="CRC"):
            parse_packet(bytes(pkt))

    def test_nack_packet_roundtrip(self):
        t, d = parse_packet(build_packet(NACK_TYPE, b""))
        assert t == NACK_TYPE


# ─────────────────────────────────────────────────────────────
# decode_type
# ─────────────────────────────────────────────────────────────

class TestDecodeType:
    """
    TYPE битовая структура:
        бит 0     — Source (0=STM32, 1=OrangePi)
        биты 2..1 — CmdType (00=запрос, 01=ответ, 10=действие, 11=ошибка)
        биты 5..3 — SysPart (000=SW, 001=Hall, 010=Voltage, 011=DHT22)
    """

    def test_action_from_orangepi(self):
        # 0x05 = 0b00000101: Source=1, CmdType=10, SysPart=000
        r = decode_type(0x05)
        assert r["source"] == 1
        assert r["cmd_type"] == 0b10
        assert r["sys_part"] == 0b000
        assert not r["is_ack"] and not r["is_nack"] and not r["is_error"]

    def test_request_hall_from_orangepi(self):
        # 0x09 = 0b00001001: Source=1, CmdType=00, SysPart=001
        r = decode_type(0x09)
        assert r["source"] == 1
        assert r["cmd_type"] == 0b00
        assert r["sys_part"] == SYS_PART_HALL   # 0b001

    def test_request_voltage_from_orangepi(self):
        # 0x11 = 0b00010001: Source=1, CmdType=00, SysPart=010
        r = decode_type(0x11)
        assert r["sys_part"] == SYS_PART_VOLTAGE  # 0b010

    def test_request_dht22_from_orangepi(self):
        # 0x19 = 0b00011001: Source=1, CmdType=00, SysPart=011
        r = decode_type(0x19)
        assert r["sys_part"] == SYS_PART_DHT22    # 0b011

    def test_ack_special_value(self):
        # ACK_TYPE = 0x40 — специальная квитанция (биты 7..6 = 01)
        r = decode_type(ACK_TYPE)
        assert r["is_ack"]
        assert not r["is_nack"]

    def test_nack_special_value(self):
        # NACK_TYPE = 0xC0 — специальная квитанция (биты 7..6 = 11)
        r = decode_type(NACK_TYPE)
        assert r["is_nack"]
        assert not r["is_ack"]

    def test_error_from_stm32_hall(self):
        # Source=0, CmdType=11, SysPart=001
        # = 0b00_001_11_0 = 0x0E
        r = decode_type(0x0E)
        assert r["source"] == 0
        assert r["is_error"]
        assert r["sys_part"] == SYS_PART_HALL

    def test_response_from_stm32_hall(self):
        # Source=0, CmdType=01 (ответ), SysPart=001
        # = 0b00_001_01_0 = 0x0A
        r = decode_type(0x0A)
        assert r["is_response"]
        assert r["sys_part"] == SYS_PART_HALL


# ─────────────────────────────────────────────────────────────
# decode_error_packet
# ─────────────────────────────────────────────────────────────

class TestDecodeErrorPacket:

    def test_hall_sensor_error(self):
        # TYPE = 0x0E: error, SysPart=Hall
        msg = decode_error_packet(0x0E, b"\x01")
        assert "Hall" in msg
        assert "1" in msg   # датчик Холла 1

    def test_software_crc_error(self):
        # TYPE: Source=0, CmdType=11, SysPart=000 (Software)
        # = 0b00_000_11_0 = 0x06
        msg = decode_error_packet(0x06, b"\x00")
        assert "Software" in msg
        assert "CRC" in msg

    def test_unknown_code_shows_code(self):
        msg = decode_error_packet(0x0E, b"\x99")
        assert "99" in msg or "0x99" in msg.upper() or "153" in msg
