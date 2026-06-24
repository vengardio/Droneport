"""
Консольная утилита: прослушка UART от STM32.

Показывает каждый принятый байт в двоичном виде.
Когда набирается полный пакет [0xBF | TYPE | LEN | DATA | CRC | 0xFF],
выводит его разбор: TYPE, LEN, DATA, CRC (совпал/нет).

Использование:
    python uart_listen.py                        # порт /dev/ttyS0, 115200
    python uart_listen.py --port COM3 --baud 9600
"""

import argparse
import sys
import time

import serial


BYTE_START   = 0xBF
BYTE_END     = 0xFF
MAX_DATA_LEN = 100


def calc_crc(type_byte: int, data: bytes) -> int:
    return (type_byte + len(data) + sum(data)) & 0xFF


def decode_packet(buf: bytearray) -> None:
    """Разобрать и вывести содержимое пакета."""
    if len(buf) < 5:
        print(f"  [ПАКЕТ СЛИШКОМ КОРОТКИЙ: {len(buf)} байт]")
        return

    type_byte = buf[1]
    declared  = buf[2]
    data      = bytes(buf[3 : 3 + declared])
    rx_crc    = buf[3 + declared] if (3 + declared) < len(buf) else -1
    calc      = calc_crc(type_byte, data)

    crc_ok = "OK" if rx_crc == calc else f"ОШИБКА (ожидали 0x{calc:02X})"

    # Source / CmdType / SysPart из TYPE-байта
    source   = type_byte & 0b00000001
    cmd_type = (type_byte & 0b00000110) >> 1
    sys_part = (type_byte & 0b00111000) >> 3

    src_str = "STM32" if source == 0 else "OrangePi"

    print()
    print("  ┌─── ПАКЕТ ─────────────────────────────")
    print(f"  │ TYPE     = 0b{type_byte:08b} (0x{type_byte:02X})")
    print(f"  │   Source   = {source} ({src_str})")
    print(f"  │   CmdType  = {cmd_type:02b}")
    print(f"  │   SysPart  = {sys_part:03b}")
    print(f"  │ LEN      = {declared}")
    if data:
        data_bin = "  ".join(f"0b{b:08b}" for b in data)
        data_hex = " ".join(f"0x{b:02X}" for b in data)
        print(f"  │ DATA bin = {data_bin}")
        print(f"  │ DATA hex = {data_hex}")
    else:
        print(f"  │ DATA     = (пусто)")
    print(f"  │ CRC      = 0x{rx_crc:02X} — {crc_ok}")
    print(f"  │ RAW      = {buf.hex(' ')}")
    print("  └────────────────────────────────────────")
    print()


def main():
    parser = argparse.ArgumentParser(description="Прослушка UART от STM32")
    parser.add_argument("--port", default="/dev/ttyS0", help="Serial порт (по умолчанию /dev/ttyS0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (по умолчанию 115200)")
    args = parser.parse_args()

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        )
        print(f"[OK] Порт {args.port} открыт @ {args.baud} бод")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось открыть {args.port}: {e}")
        sys.exit(1)

    print()
    print("=== UART LISTEN — прослушка STM32 ===")
    print("Каждый байт выводится в двоичном виде.")
    print("Полные пакеты разбираются автоматически.")
    print("Ctrl+C — выход.")
    print()

    buf       = bytearray()
    in_packet = False
    declared  = None
    last_byte_time = 0.0
    INTER_BYTE_TIMEOUT = 0.3  # 300 мс — если между байтами прошло больше, сбрасываем

    try:
        while True:
            chunk = ser.read(64)
            if not chunk:
                # Проверяем межбайтовый таймаут для незавершённого пакета
                if in_packet and (time.monotonic() - last_byte_time) > INTER_BYTE_TIMEOUT:
                    print(f"  [ТАЙМАУТ] Незавершённый пакет ({len(buf)} байт): {buf.hex(' ')}")
                    buf.clear()
                    in_packet = False
                    declared  = None
                continue

            now = time.monotonic()

            for byte in chunk:
                # Таймаут внутри пакета — сбросить
                if in_packet and (now - last_byte_time) > INTER_BYTE_TIMEOUT:
                    print(f"  [ТАЙМАУТ] Сброс ({len(buf)} байт): {buf.hex(' ')}")
                    buf.clear()
                    in_packet = False
                    declared  = None

                last_byte_time = now

                # Вывод каждого байта
                marker = ""
                if byte == BYTE_START:
                    marker = " ← START"
                elif byte == BYTE_END and in_packet:
                    marker = " ← END"

                ts = time.strftime("%H:%M:%S")
                print(f"  [{ts}]  0b{byte:08b}  (0x{byte:02X}  dec={byte:3d}){marker}")

                # Ищем начало пакета
                if not in_packet:
                    if byte == BYTE_START:
                        in_packet = True
                        buf.clear()
                        buf.append(byte)
                        declared = None
                    continue

                # Набираем пакет
                buf.append(byte)

                # Узнали LEN
                if len(buf) == 3:
                    declared = buf[2]
                    if declared > MAX_DATA_LEN:
                        print(f"  [ОШИБКА] LEN={declared} > {MAX_DATA_LEN}, сброс")
                        buf.clear()
                        in_packet = False
                        declared  = None
                        continue

                # Проверяем конец пакета
                packet_done = False

                if byte == BYTE_END and len(buf) >= 5:
                    packet_done = True

                if declared is not None and len(buf) >= (3 + declared + 2):
                    packet_done = True

                if packet_done:
                    decode_packet(buf)
                    buf.clear()
                    in_packet = False
                    declared  = None

    except KeyboardInterrupt:
        print("\nВыход.")

    ser.close()
    print(f"Порт {args.port} закрыт.")


if __name__ == "__main__":
    main()
