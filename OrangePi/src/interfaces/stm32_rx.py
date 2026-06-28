"""
Приём пакетов от STM32 (побайтовая сборка).

Пакет: [0xBF | TYPE | LEN | DATA | CRC | 0xFF]
CRC = (TYPE + LEN + sum(DATA)) & 0xFF
"""

import time
import serial

BYTE_START         = 0xBF
BYTE_END           = 0xFF
MAX_DATA           = 100
INTER_BYTE_TIMEOUT = 0.15   # сек между байтами внутри пакета


class STM32RxError(Exception):
    pass


def _parse_packet(raw: bytes) -> tuple:
    if len(raw) < 5:
        raise STM32RxError(f"Пакет слишком короткий: {len(raw)} байт")
    if raw[0] != BYTE_START:
        raise STM32RxError(f"Нет BYTE_START: 0x{raw[0]:02X}")
    if raw[-1] != BYTE_END:
        raise STM32RxError(f"Нет BYTE_END: 0x{raw[-1]:02X}")

    type_byte = raw[1]
    declared  = raw[2]
    data      = raw[3 : 3 + declared]
    rx_crc    = raw[3 + declared]

    if len(data) != declared:
        raise STM32RxError("Длина DATA не совпадает с объявленной")
    calc_crc = (type_byte + len(data) + sum(data)) & 0xFF
    if rx_crc != calc_crc:
        raise STM32RxError(f"CRC ошибка: rx=0x{rx_crc:02X}, calc=0x{calc_crc:02X}")

    return type_byte, data


def recv_packet(ser: serial.Serial, timeout_sec: float = 2.0) -> tuple:
    """
    Собрать один пакет от STM32.
    Ждём BYTE_START не дольше timeout_sec.
    После первого байта — межбайтовый таймаут INTER_BYTE_TIMEOUT.
    Возвращает (type_byte, data) или бросает STM32RxError / TimeoutError.
    """
    buf       = bytearray()
    started   = False
    declared  = None
    deadline  = time.monotonic() + timeout_sec
    last_byte = time.monotonic()

    while True:
        now = time.monotonic()

        if not started and now > deadline:
            raise TimeoutError(f"STM32 не ответил за {timeout_sec:.1f}с")

        if started and (now - last_byte) > INTER_BYTE_TIMEOUT:
            raise STM32RxError(f"Межбайтовый таймаут, собрано {len(buf)} байт: {buf.hex()}")

        chunk = ser.read(64)
        if not chunk:
            continue

        last_byte = time.monotonic()
        done = False

        for byte in chunk:
            if not started:
                if byte == BYTE_START:
                    started = True
                    buf.clear()
                    buf.append(byte)
                continue

            buf.append(byte)

            if len(buf) == 3:
                declared = buf[2]
                if declared > MAX_DATA:
                    raise STM32RxError(f"LEN слишком большой: {declared}")

            if byte == BYTE_END and len(buf) >= 5:
                done = True
                break

            if declared is not None and len(buf) >= (3 + declared + 2):
                done = True
                break

        if done:
            break

    return _parse_packet(bytes(buf))
