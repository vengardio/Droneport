import argparse
import sys

import serial


BYTE_START = 0xBF
BYTE_END   = 0xFF


def calc_crc(type_byte: int, data: bytes) -> int:
    return (type_byte + len(data) + sum(data)) & 0xFF


def build_packet(type_byte: int, data: bytes) -> bytes:
    crc = calc_crc(type_byte, data)
    return bytes([BYTE_START, type_byte, len(data)]) + data + bytes([crc, BYTE_END])


def fmt_binary(raw: bytes) -> str:
    parts = []
    for b in raw:
        parts.append(f"0b{b:08b} (0x{b:02X})")
    return "\n  ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Отправка пакетов на STM32 через UART")
    parser.add_argument(
        "--port", default="/dev/ttyS3", help="Serial порт (по умолчанию /dev/ttyS3)"
    )
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (по умолчанию 115200)")
    args = parser.parse_args()

    try:
        ser = serial.Serial(
            port=args.port,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )
        print(f"[OK] Порт {args.port} открыт @ {args.baud} бод")
    except Exception as e:
        print(f"[ОШИБКА] Не удалось открыть {args.port}: {e}")
        sys.exit(1)

    print()
    print("=== UART SEND — отправка пакетов на STM32 ===")
    print("Протокол: [0xBF | TYPE | LEN | DATA | CRC | 0xFF]")
    print()
    print("Формат ввода:")
    print("  TYPE (hex)  — 1 байт, например: 05")
    print("  DATA (hex)  — 0+ байт через пробел, например: 11 или пусто")
    print("  'q' — выход")
    print()

    while True:
        try:
            raw_input = input("TYPE DATA > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if not raw_input or raw_input.lower() == "q":
            print("Выход.")
            break

        # --- Парсинг ввода ---
        tokens = raw_input.split()
        try:
            type_byte = int(tokens[0], 16)
            data = bytes([int(t, 16) for t in tokens[1:]])
        except (ValueError, IndexError):
            print("[ОШИБКА] Формат: TYPE_HEX [DATA_HEX ...].  Пример: 05 16")
            continue

        if type_byte > 0xFF:
            print("[ОШИБКА] TYPE должен быть 1 байт (00..FF)")
            continue
        if len(data) > 100:
            print(f"[ОШИБКА] DATA слишком длинная: {len(data)} > 100 байт")
            continue

        # --- Сборка и отправка ---
        packet = build_packet(type_byte, data)

        print()
        print(f"  Пакет ({len(packet)} байт):")
        print(f"  {fmt_binary(packet)}")
        print()
        print(f"  HEX: {packet.hex(' ')}")
        print(f"  TYPE=0x{type_byte:02X}  LEN={len(data)}  CRC=0x{calc_crc(type_byte, data):02X}")
        print()

        try:
            ser.write(packet)
            print(f"  [ОТПРАВЛЕНО] {len(packet)} байт")
        except Exception as e:
            print(f"  [ОШИБКА] {e}")

        print()

    ser.close()
    print(f"Порт {args.port} закрыт.")


if __name__ == "__main__":
    main()
