"""
UART транспорт для STM32.

Пакет: [0xBF | TYPE | LEN | DATA | CRC | 0xFF]
CRC = (TYPE + LEN + sum(DATA)) & 0xFF

ACK = 0x40, NACK = 0xC0 (за NACK следует Error-пакет).
"""

import asyncio
import logging
import time
from typing import Optional

import serial  # pyserial

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Константы протокола
# ──────────────────────────────────────────────────────────────
BYTE_START           = 0xBF
BYTE_END             = 0xFF
MAX_DATA_LEN         = 100
MAX_PACKET_LEN       = 3 + MAX_DATA_LEN + 2   # 105 байт

ACK_TYPE             = 0b01000000   # 0x40 — успешная квитанция
NACK_TYPE            = 0b11000000   # 0xC0 — ошибочная квитанция
ERROR_TYPE_SOFTWARE  = 0b00000110   # Source=0, CmdType=11, SysPart=000

SOURCE_MASK          = 0b00000001   # бит 0: 0=STM32, 1=OrangePi
CMD_TYPE_MASK        = 0b00000110   # биты 2..1
SYS_PART_MASK        = 0b00111000   # биты 5..3

INTER_BYTE_TIMEOUT_SEC = 0.15       # 150 мс (с запасом к 100 мс на STM32)
READ_CHUNK             = 64         # байт за одно serial.read()


# ──────────────────────────────────────────────────────────────
# Исключение
# ──────────────────────────────────────────────────────────────
class STM32PacketError(Exception):
    """Ошибка на уровне пакета STM32."""
    pass


# ──────────────────────────────────────────────────────────────
# Утилиты пакета
# ──────────────────────────────────────────────────────────────
def calc_checksum(type_byte: int, data: bytes) -> int:
    """CRC = (TYPE + LEN + sum(DATA)) % 256. Без BYTE_START, BYTE_END и самого CRC."""
    return (type_byte + len(data) + sum(data)) & 0xFF


def build_packet(type_byte: int, data: bytes = b"") -> bytes:
    """Собрать пакет: [BYTE_START | TYPE | LEN | DATA | CRC | BYTE_END]."""
    if len(data) > MAX_DATA_LEN:
        raise ValueError(f"DATA слишком длинная: {len(data)} > {MAX_DATA_LEN}")
    crc = calc_checksum(type_byte, data)
    return bytes([BYTE_START, type_byte, len(data)]) + data + bytes([crc, BYTE_END])


def parse_packet(raw: bytes) -> tuple[int, bytes]:
    """
    Разобрать сырой буфер → (type_byte, data).
    Проверяет маркеры и CRC. Бросает STM32PacketError при ошибке.
    """
    if len(raw) < 5:
        raise STM32PacketError(f"Пакет слишком короткий: {len(raw)} байт")
    if raw[0] != BYTE_START:
        raise STM32PacketError(f"Нет BYTE_START: 0x{raw[0]:02X}")
    if raw[-1] != BYTE_END:
        raise STM32PacketError(f"Нет BYTE_END: 0x{raw[-1]:02X}")

    type_byte = raw[1]
    declared  = raw[2]
    data      = raw[3 : 3 + declared]
    rx_crc    = raw[3 + declared]
    calc_crc  = calc_checksum(type_byte, data)

    if len(data) != declared:
        raise STM32PacketError(
            f"Длина DATA не совпадает: объявлено {declared}, получено {len(data)}"
        )
    if rx_crc != calc_crc:
        raise STM32PacketError(
            f"CRC ошибка: получено 0x{rx_crc:02X}, ожидалось 0x{calc_crc:02X}"
        )
    return type_byte, data


# ──────────────────────────────────────────────────────────────
# Транспортный уровень
# ──────────────────────────────────────────────────────────────
class STM32Transport:
    """
    Физический UART порт: открыть/закрыть, отправить/принять пакет.
    pyserial + asyncio.to_thread(), мьютекс на одну транзакцию.
    """

    def __init__(
        self,
        port:     str = "/dev/ttyS0",
        baudrate: int = 115200,
        logger:   Optional[logging.Logger] = None,
    ):
        self._port     = port
        self._baudrate = baudrate
        self._ser:     Optional[serial.Serial] = None
        self._lock     = asyncio.Lock()
        self.log       = logger or log

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Открыть serial-порт. Вернуть True при успехе."""
        def _open():
            return serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=INTER_BYTE_TIMEOUT_SEC,
            )
        try:
            self._ser = await asyncio.to_thread(_open)
            self.log.info("STM32 UART открыт: %s @ %d", self._port, self._baudrate)
            return True
        except Exception as e:
            self.log.error("Не удалось открыть %s: %s", self._port, e)
            return False

    async def disconnect(self) -> None:
        """Закрыть serial-порт."""
        if self._ser and self._ser.is_open:
            await asyncio.to_thread(self._ser.close)
            self.log.info("STM32 UART закрыт")
        self._ser = None

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # ------------------------------------------------------------------
    # Отправка
    # ------------------------------------------------------------------

    async def send_raw(self, data: bytes) -> None:
        if not self.is_connected:
            raise STM32PacketError("Порт не открыт")
        await asyncio.to_thread(self._ser.write, data)
        self.log.debug("→ STM32 %d байт: %s", len(data), data.hex())

    async def send_packet(self, type_byte: int, data: bytes = b"") -> None:
        pkt = build_packet(type_byte, data)
        await self.send_raw(pkt)

    # ------------------------------------------------------------------
    # Приём одного пакета
    # ------------------------------------------------------------------

    async def recv_packet(self, timeout_sec: float = 2.0) -> tuple[int, bytes]:
        """
        Принять один пакет от STM32.

        Конец пакета — первое из трёх условий:
            1. Получен байт BYTE_END
            2. Накоплено ровно (3 + LEN + 2) байт
            3. Межбайтовый таймаут INTER_BYTE_TIMEOUT_SEC

        timeout_sec — максимальное ожидание первого байта (BYTE_START).
        Бросает TimeoutError или STM32PacketError.
        """
        if not self.is_connected:
            raise STM32PacketError("Порт не открыт")

        buf       = bytearray()
        started   = False
        declared  = None
        deadline  = time.monotonic() + timeout_sec
        last_byte = time.monotonic()

        while True:
            now = time.monotonic()

            # Таймаут ожидания первого байта
            if not started and now > deadline:
                raise TimeoutError(f"STM32 не ответил за {timeout_sec:.1f}с")

            # Межбайтовый таймаут внутри пакета
            if started and (now - last_byte) > INTER_BYTE_TIMEOUT_SEC:
                self.log.warning(
                    "Межбайтовый таймаут после %d байт: %s", len(buf), buf.hex()
                )
                break

            chunk = await asyncio.to_thread(self._ser.read, READ_CHUNK)
            if not chunk:
                await asyncio.sleep(0)
                continue

            last_byte = time.monotonic()
            packet_done = False

            for byte in chunk:
                if not started:
                    if byte == BYTE_START:
                        started = True
                        buf.clear()
                        buf.append(byte)
                    continue

                buf.append(byte)

                # Узнали LEN — вычисляем ожидаемую длину пакета
                if len(buf) == 3:
                    declared = buf[2]
                    if declared > MAX_DATA_LEN:
                        self.log.error(
                            "LEN слишком большой: %d > %d, сбрасываем", declared, MAX_DATA_LEN
                        )
                        buf.clear()
                        started  = False
                        declared = None
                        continue

                # Условие 1: стоп-байт
                if byte == BYTE_END and len(buf) >= 5:
                    packet_done = True
                    break

                # Условие 2: набрали ровно нужное количество байт
                if declared is not None and len(buf) >= (3 + declared + 2):
                    packet_done = True
                    break

            if packet_done:
                break

            await asyncio.sleep(0)

        if not buf:
            raise STM32PacketError("Пустой буфер после приёма")

        type_byte, data = parse_packet(bytes(buf))
        self.log.debug(
            "← STM32 TYPE=0x%02X LEN=%d DATA=%s", type_byte, len(data), data.hex()
        )
        return type_byte, data

    # ------------------------------------------------------------------
    # Транзакция: отправить → получить → проверить ACK/NACK
    # ------------------------------------------------------------------

    async def transact(
        self,
        type_byte:   int,
        data:        bytes = b"",
        timeout_sec: float = 2.0,
    ) -> tuple[int, bytes]:
        """
        Полная транзакция (под мьютексом):
            1. Отправить пакет
            2. Получить ответный пакет
            3. Если NACK — прочитать Error-пакет и бросить STM32PacketError
            4. Вернуть (type, data) ответа

        Мьютекс гарантирует: только одна транзакция за раз.
        """
        async with self._lock:
            await self.send_packet(type_byte, data)
            resp_type, resp_data = await self.recv_packet(timeout_sec)

            if resp_type == NACK_TYPE:
                try:
                    _, err_data = await self.recv_packet(timeout_sec=1.0)
                    err_code = err_data[0] if err_data else -1
                except Exception:
                    err_code = -1
                raise STM32PacketError(f"STM32 вернул NACK, код ошибки: {err_code}")

            return resp_type, resp_data


# ──────────────────────────────────────────────────────────────
# Фасад — публичный API для command_handlers.py
# ──────────────────────────────────────────────────────────────
class STM32Interface:
    """
    Фасад STM32 для command_handlers.py.
    Методы: send_action, read_hall_sensors, read_voltage, read_dht22.
    При ошибках возвращает None/False (исключения не пробрасывает).
    """

    def __init__(
        self,
        port:     str = "/dev/ttyS0",
        baudrate: int = 115200,
        logger:   Optional[logging.Logger] = None,
    ):
        self._transport = STM32Transport(port=port, baudrate=baudrate, logger=logger)
        self.log = logger or log

        # Импорт TX/RX здесь (не на уровне модуля) — разрываем циклический импорт.
        # uart_stm32_tx и uart_stm32_rx сами делают from .uart_stm32_init import ...,
        # поэтому их нельзя импортировать в верхней части этого файла.
        from .uart_stm32_tx import STM32TX
        from .uart_stm32_rx import STM32RX
        self._tx = STM32TX(self._transport)
        self._rx = STM32RX(self._transport)

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        return await self._transport.connect()

    async def disconnect(self) -> None:
        await self._transport.disconnect()

    @property
    def is_connected(self) -> bool:
        return self._transport.is_connected

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def send_action(self, code: int) -> bool:
        return await self._tx.send_action(code)

    async def read_hall_sensors(self) -> Optional[int]:
        return await self._tx.request_hall_sensors()

    async def read_voltage(self) -> Optional[float]:
        return await self._tx.request_voltage()

    async def read_dht22(self) -> Optional[tuple[float, float]]:
        return await self._tx.request_dht22()

    # ------------------------------------------------------------------
    # Диагностика
    # ------------------------------------------------------------------

    async def drain(self) -> None:
        """Вычитать мусор из порта при старте (после сброса STM32)."""
        packets = await self._rx.drain_unexpected(timeout_sec=0.5)
        if packets:
            self.log.info("Вычищено %d незапрошенных пакетов от STM32", len(packets))