"""
src/core/command_handlers.py

Архитектура:
  - Каждый handler кладёт задачу в asyncio.Queue через _enqueue()
  - Единственный _worker() выполняет задачи по одной — никакого параллелизма
  - Шаги сценария разворачиваются прямо здесь, читая scenarios.json
  - STOP/RETURN — приоритетные: очередь сбрасывается немедленно

Добавить новый хендлер:
  1. async def handle_X(self, packet) → _enqueue(self._run_X, packet)
  2. async def _run_X(self, packet)   → _run_scenario_steps("X", packet)
  3. Зарегистрировать в register_all()
"""

import asyncio
import json
import logging
import struct
from pathlib import Path
from typing import Optional

from src.interfaces.udp_server_rx import ServerCommand
from src.services.error_handler   import Severity

logger = logging.getLogger(__name__)

BASE_DIR       = Path(__file__).parent.parent.parent
SCENARIOS_PATH = BASE_DIR / "config" / "scenarios.json"
MAX_HALL_RETRIES = 3


# ---------------------------------------------------------------------------
# Загрузка сценариев
# ---------------------------------------------------------------------------

def load_scenarios() -> dict:
    with open(SCENARIOS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info("Загружено сценариев: %d", len(data))
    return data


# ---------------------------------------------------------------------------
# Вспомогательная функция: таймаут по ключу из hardware.yaml
# ---------------------------------------------------------------------------

def _resolve_timeout(
    step:         dict,
    hardware_cfg: dict,
    category:     str,
    default:      float = 20.0,
) -> float:
    """Достать таймаут из hardware_cfg по ключу шага, с фолбэком в action_timeouts."""
    key = step.get("timeout_key")
    if key is None:
        return default

    value = hardware_cfg.get(category, {}).get(key)
    if value is not None:
        return float(value)

    # Фолбэк: поискать в action_timeouts
    fallback = hardware_cfg.get("action_timeouts", {}).get(key)
    return float(fallback) if fallback is not None else default


# ---------------------------------------------------------------------------
# Исполнители отдельных типов шагов
# (вынесены как обычные функции — легко тестировать отдельно)
# ---------------------------------------------------------------------------

async def execute_stm32_action(
    step:         dict,
    uart_stm32,
    hardware_cfg: dict,
) -> None:
    """Послать action_code на STM32, при verify_hall — проверить нужный бит. Ретраи MAX_HALL_RETRIES раз."""
    action_code  = step["action_code"]
    error_code   = step.get("error_code", "MECHANICS")
    timeout_sec  = _resolve_timeout(step, hardware_cfg, "action_timeouts", default=5.0)

    # --- заглушка ---
    if uart_stm32 is None:
        logger.debug("[STUB] stm32_action code=%d → OK (без ожидания)", action_code)
        await asyncio.sleep(0)
        return

    # --- реальное железо ---
    verify_hall = step.get("verify_hall", False)

    for attempt in range(1, MAX_HALL_RETRIES + 1):

        ok = await uart_stm32.send_action(action_code)
        if not ok:
            raise RuntimeError(
                f"[{error_code}] STM32 не принял action_code={action_code}"
            )

        logger.debug(
            "STM32 action=%d, ждём %.1fс (попытка %d/%d)",
            action_code, timeout_sec, attempt, MAX_HALL_RETRIES,
        )
        await asyncio.sleep(timeout_sec)

        if not verify_hall:
            return

        expected_bit = step["expected_hall_bit"]
        expected_val = step["bit_value"]
        hall_byte    = await uart_stm32.read_hall_sensors()
        actual_bit   = (hall_byte >> expected_bit) & 1

        if actual_bit == expected_val:
            logger.debug("Холл бит %d = %d — ОК", expected_bit, expected_val)
            return

        logger.warning(
            "Холл бит %d = %d, ожидали %d (попытка %d/%d)",
            expected_bit, actual_bit, expected_val, attempt, MAX_HALL_RETRIES,
        )

    raise RuntimeError(
        f"[{error_code}] Холл бит {step['expected_hall_bit']} "
        f"не в нужном состоянии после {MAX_HALL_RETRIES} попыток"
    )


async def execute_stm32_request(step: dict, uart_stm32) -> object:
    """
    Запросить данные у STM32.

    system_part:
        1 → датчики Холла (uint8, побитовая карта)
        2 → напряжение АКБ (float В)
        3 → DHT22 (tuple: температура °C, влажность %)

    Заглушка (uart_stm32=None): возвращает правдоподобные дефолты.
    """
    system_part = step["system_part"]
    error_code  = step.get("error_code", "MECHANICS")

    # --- заглушка ---
    if uart_stm32 is None:
        stubs = {
            1: 0b01001010,   # крыша закрыта (бит1), стол внизу (бит3), лапки сжаты (бит6)
            2: 12.6,         # напряжение АКБ в норме
            3: (22.5, 45.0), # температура и влажность
        }
        result = stubs.get(system_part)
        if result is not None:
            logger.debug("[STUB] stm32_request system_part=%d → %s", system_part, result)
            return result
        raise RuntimeError(f"Неизвестный system_part={system_part}")

    # --- реальное железо ---
    if system_part == 1:
        hall_byte   = await uart_stm32.read_hall_sensors()
        assert_bits = step.get("assert_bits", {})
        for bit_str, expected_val in assert_bits.items():
            bit    = int(bit_str)
            actual = (hall_byte >> bit) & 1
            if actual != expected_val:
                raise RuntimeError(
                    f"[{error_code}] Исходное положение нарушено: "
                    f"бит Холла {bit} = {actual}, ожидается {expected_val}"
                )
        return hall_byte

    if system_part == 2:
        voltage   = await uart_stm32.read_voltage()
        min_value = step.get("min_value")
        if min_value is not None and voltage < min_value:
            raise RuntimeError(
                f"[{error_code}] АКБ {voltage:.1f}В ниже порога {min_value}В"
            )
        return voltage

    if system_part == 3:
        return await uart_stm32.read_dht22()

    raise RuntimeError(f"Неизвестный system_part={system_part}")


async def execute_wait_radio(
    step:         dict,
    radio_link,
    udp_tx,
    hardware_cfg: dict,
) -> bytes:
    """
    Ждать конкретный CMD от БПЛА, попутно ретранслируя relay_cmds серверу.

    Аналогия: ждёшь автобус №44 (BOARDING_REQUEST). Все автобусы №41
    (TELEMETRY_SLOW) что проезжают мимо — показываешь диспетчеру (серверу).
    Не дождался за timeout — RuntimeError.
    """
    expected_cmd = step["expected_cmd"]
    timeout_sec  = _resolve_timeout(step, hardware_cfg, "radio_timeouts", default=20.0)
    relay_cmds   = set(step.get("relay_cmds", []))
    deadline     = asyncio.get_event_loop().time() + timeout_sec

    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise RuntimeError(
                f"[DRONE_NO_RESPONSE] Таймаут {timeout_sec}с: "
                f"БПЛА не прислал CMD={expected_cmd}"
            )

        try:
            radio_cmd, radio_data = await asyncio.wait_for(
                radio_link.receive_packet(), timeout=remaining
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"[DRONE_NO_RESPONSE] Таймаут {timeout_sec}с: "
                f"БПЛА не прислал CMD={expected_cmd}"
            )

        if radio_cmd in relay_cmds:
            await udp_tx.send_packet(cmd=radio_cmd, data=radio_data)
            logger.debug("Ретрансляция CMD=%d серверу (%d байт)", radio_cmd, len(radio_data))

        if radio_cmd == expected_cmd:
            logger.debug("Получен ожидаемый CMD=%d от БПЛА", expected_cmd)
            return radio_data


async def execute_usb_sensor(
    step:         dict,
    usb_sensors,
    hardware_cfg: dict,
) -> object:
    """
    Получить данные от USB-датчика (gps / weather).
    Таймаут из hardware_cfg["sensor_timeouts"][timeout_key].

    Заглушка (usb_sensors=None): возвращает фиксированные тестовые данные.
    """
    sensor      = step["sensor"]
    timeout_sec = _resolve_timeout(step, hardware_cfg, "sensor_timeouts", default=20.0)
    require_fix = step.get("require_fix", False)
    error_code  = step.get("error_code", "POSITION_LOST")

    # --- заглушка ---
    if usb_sensors is None:
        stubs = {
            "gps": {
                "latitude": 55.751244, "longitude": 37.618423,
                "altitude": 156.0, "fix_quality": 1, "satellites": 8,
            },
            "weather": {
                "temperature_inside": 22.0, "temperature_outside": 5.0,
                "wind_speed": 3, "wind_direction": 180, "humidity": 60,
            },
        }
        result = stubs.get(sensor)
        if result is None:
            raise RuntimeError(f"Неизвестный USB-датчик: '{sensor}'")
        logger.debug("[STUB] usb_sensor %s → %s", sensor, result)
        return result

    # --- реальное железо ---
    try:
        if sensor == "gps":
            result = await asyncio.wait_for(
                usb_sensors.get_coordinates(), timeout=timeout_sec
            )
            if require_fix and result.get("fix_quality", 0) == 0:
                raise RuntimeError(f"[{error_code}] GPS не дал фикс за {timeout_sec}с")
            return result

        if sensor == "weather":
            return await asyncio.wait_for(
                usb_sensors.read_weather(), timeout=timeout_sec
            )

        raise RuntimeError(f"Неизвестный USB-датчик: '{sensor}'")

    except asyncio.TimeoutError:
        raise RuntimeError(
            f"[{error_code}] Датчик '{sensor}' не ответил за {timeout_sec}с"
        )


async def execute_weather_request(
    step:            dict,
    weather_station,
    hardware_cfg:    dict,
) -> object:
    """
    Запросить данные у Arduino метеостанции (UART).
    Таймаут из hardware_cfg["sensor_timeouts"]["weather"].

    Заглушка (weather_station=None): возвращает фиксированные тестовые данные.
    """
    timeout_sec = _resolve_timeout(step, hardware_cfg, "sensor_timeouts", default=5.0)
    error_code  = step.get("error_code", "TEMP_SENSOR_FAIL")

    # --- заглушка ---
    if weather_station is None:
        stub = {
            "wind_dir": 180,
            "wind_speed": 30,        # 3.0 м/с × 10
            "temperature": 5.0,
            "humidity": 60.0,
        }
        logger.debug("[STUB] weather_request → %s", stub)
        return stub

    # --- реальное железо ---
    try:
        result = await asyncio.wait_for(
            weather_station.read_weather(), timeout=timeout_sec
        )
        if result is None:
            raise RuntimeError(f"[{error_code}] Метеостанция вернула None")
        return result

    except asyncio.TimeoutError:
        raise RuntimeError(
            f"[{error_code}] Метеостанция не ответила за {timeout_sec}с"
        )


def serialize_store_value(val) -> bytes:
    """Сериализовать значение из store в байты для отправки серверу."""
    if isinstance(val, bytes):
        return val
    if isinstance(val, int):
        return struct.pack("B", val & 0xFF)
    if isinstance(val, float):
        return struct.pack("<H", int(val * 10))
    if isinstance(val, tuple) and len(val) == 2:
        temp, hum = val
        return struct.pack("<hh", int(temp * 10), int(hum * 10))
    if isinstance(val, dict):
        result = b""
        for v in val.values():
            if isinstance(v, int):
                result += struct.pack("<i", v)
            elif isinstance(v, float):
                result += struct.pack("<i", int(v * 1e7))
        return result
    logger.warning("Не знаю как сериализовать %s, пропускаем", type(val))
    return b""


# ---------------------------------------------------------------------------
# CommandHandlers
# ---------------------------------------------------------------------------

class CommandHandlers:
    """
    Точка входа для всех команд от сервера.

    Жизненный цикл команды:
        handle_X(packet)          — принять, ACK, положить в очередь
        _worker()                 — взять из очереди, выполнить
        _run_X(packet)            — вызвать _run_scenario_steps()
        _run_scenario_steps()     — пройти шаги JSON-сценария
        _dispatch_step()          — выбрать и вызвать execute_* функцию
    """

    def __init__(
        self,
        udp_tx,
        uart_stm32,
        radio_link,
        usb_sensors,
        weather_station,
        error_handler,
        hardware_cfg: dict,
        droneport_id: int,
    ):
        self.udp_tx          = udp_tx
        self.uart_stm32      = uart_stm32
        self.radio_link      = radio_link
        self.usb_sensors     = usb_sensors
        self.weather_station = weather_station
        self.error_handler   = error_handler
        self.hardware_cfg    = hardware_cfg
        self.droneport_id    = droneport_id

        self._scenarios = load_scenarios()
        self._queue: asyncio.Queue = asyncio.Queue()

    # ------------------------------------------------------------------
    # Воркер очереди
    # ------------------------------------------------------------------

    def start_worker(self) -> asyncio.Task:
        """Запустить фоновый воркер. Вызывать из main.py один раз."""
        return asyncio.create_task(self._worker(), name="cmd_worker")

    async def _worker(self) -> None:
        """Бесконечный цикл: берёт задачи из очереди по одной."""
        logger.info("CommandHandlers worker запущен")
        while True:
            coro_factory, packet = await self._queue.get()
            try:
                await coro_factory(packet)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Worker: ошибка в задаче CMD=%d: %s", packet.cmd, exc)
            finally:
                self._queue.task_done()

    def _enqueue(self, coro_factory, packet) -> None:
        self._queue.put_nowait((coro_factory, packet))
        logger.debug(
            "CMD=%d добавлен в очередь (в очереди: %d)",
            packet.cmd, self._queue.qsize(),
        )

    def _clear_queue(self) -> None:
        """Сбросить всё из очереди. Используется при STOP и RETURN."""
        dropped = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        if dropped:
            logger.warning("Очередь сброшена, отброшено %d команд", dropped)

    # ------------------------------------------------------------------
    # Регистрация хендлеров
    # ------------------------------------------------------------------

    def register_all(self, rx_module) -> None:
        """Зарегистрировать все хендлеры в UDPServerRX. Вызывать из main.py."""
        from src.interfaces.udp_server_rx import ServerCommand

        mapping = {
            ServerCommand.OPEN_DRONPORT:       self.handle_open_droneport,
            ServerCommand.CLOSE_DRONPORT:      self.handle_close_droneport,
            ServerCommand.DIAGNOSTIC:          self.handle_diagnostic,
            ServerCommand.CONDITION_DRON:      self.handle_condition_dron,
            ServerCommand.EXTERNAL_PARAM:      self.handle_external_param,
            ServerCommand.REQUEST_COORDINATE:  self.handle_request_coordinate,
            ServerCommand.STATUS_SHUTTERS:     self.handle_status_shutters,
            ServerCommand.STATUS:              self.handle_status,
            ServerCommand.COMBAT_MODE:         self.handle_combat_mode,
            ServerCommand.TARGET_INTERCEPTION: self.handle_target_interception,
            ServerCommand.DEMO_MODE:           self.handle_demo_mode,
            ServerCommand.SECTOR_SEARCH:       self.handle_sector_search,
            ServerCommand.DIAGNOSTIC_FLIGHT:   self.handle_diagnostic_flight,
            ServerCommand.DRONE_FLIGHT:        self.handle_drone_flight,
            ServerCommand.STOP:                self.handle_stop,
            ServerCommand.RETURN:              self.handle_return,
            ServerCommand.PRE_FLIGHT:          self.handle_pre_flight,
            ServerCommand.COORDINATE_NED:      self.handle_coordinate_ned,
            ServerCommand.DRONE_COMM_STATUS:   self.handle_drone_comm_status,
        }
        for cmd, handler in mapping.items():
            rx_module.register_handler(cmd, handler)

        logger.info("Зарегистрировано %d хендлеров", len(mapping))

    # ------------------------------------------------------------------
    # Движок сценариев
    # ------------------------------------------------------------------

    async def _run_scenario_steps(
        self,
        scenario_name:  str,
        packet,
        scenario_input: Optional[bytes] = None,
    ) -> None:
        """
        Читает шаги из scenarios.json и выполняет их по одному.
        При ошибке и abort_on_error=true — прерывает сценарий и сообщает серверу.
        """
        scenario = self._scenarios.get(scenario_name)
        if scenario is None:
            raise RuntimeError(f"Сценарий '{scenario_name}' не найден в scenarios.json")

        abort_on_error   = scenario.get("abort_on_error", True)
        sends_drone_comm = scenario.get("sends_drone_comm", False)
        store: dict      = {}

        logger.info("[%s] Начало (%d шагов)", scenario_name, len(scenario.get("steps", [])))

        if sends_drone_comm:
            await self.udp_tx.send_packet(cmd=51, data=bytes([1]))

        try:
            for step in scenario.get("steps", []):
                step_id = step.get("step_id", "?")
                logger.debug("[%s] Шаг %s (%s)", scenario_name, step_id, step["type"])

                try:
                    await self._dispatch_step(step, store, scenario_name, scenario_input)

                except asyncio.CancelledError:
                    logger.warning("[%s] Шаг %s прерван (STOP/RETURN)", scenario_name, step_id)
                    raise

                except Exception as exc:
                    error_code = self._extract_error_code(str(exc))
                    logger.error("[%s] Шаг %s провалился: %s", scenario_name, step_id, exc)
                    await self.error_handler.report_error(
                        code=error_code, message=str(exc), severity=Severity.ERROR
                    )
                    if abort_on_error:
                        await self.udp_tx.send_packet(cmd=30, data=struct.pack("bb", -1, 0))
                        return

            logger.info("[%s] Завершён успешно", scenario_name)

        finally:
            if sends_drone_comm:
                await self.udp_tx.send_packet(cmd=51, data=bytes([2]))

    async def _dispatch_step(
        self,
        step:           dict,
        store:          dict,
        scenario_name:  str,
        scenario_input: Optional[bytes],
    ) -> None:
        """Диспетчер: смотрит на step["type"] и вызывает нужную функцию."""
        t        = step["type"]
        store_as = step.get("store_as")

        if t == "stm32_action":
            await execute_stm32_action(step, self.uart_stm32, self.hardware_cfg)

        elif t == "stm32_request":
            result = await execute_stm32_request(step, self.uart_stm32)
            if store_as:
                store[store_as] = result

        elif t == "radio_command":
            await self._step_radio_command(step, store, scenario_input)

        elif t == "wait_radio":
            await self._step_wait_radio(step, store)

        elif t == "usb_sensor":
            result = await execute_usb_sensor(step, self.usb_sensors, self.hardware_cfg)
            if store_as:
                store[store_as] = result

        elif t == "weather_request":
            result = await execute_weather_request(step, self.weather_station, self.hardware_cfg)
            if store_as:
                store[store_as] = result

        elif t == "send_server":
            await self._step_send_server(step, store)

        elif t == "sub_scenario":
            await self._step_sub_scenario(step, store, scenario_name, scenario_input)

        else:
            raise RuntimeError(f"Неизвестный тип шага: '{t}'")

    async def _step_radio_command(
        self,
        step:           dict,
        store:          dict,
        scenario_input: Optional[bytes],
    ) -> None:
        if self.radio_link is None:
            logger.debug("[STUB] radio_command CMD=%d → OK", step["cmd"])
            return

        data_source = step.get("data_source")
        if data_source is None:
            data = b""
        elif data_source == "scenario_input":
            data = scenario_input or b""
        elif isinstance(data_source, str) and data_source.startswith("stored:"):
            data = store.get(data_source.split(":", 1)[1], b"")
        else:
            data = b""

        ok = await self.radio_link.send_command(step["cmd"], data)
        if not ok:
            raise RuntimeError("[DRONE_NO_RESPONSE] radio_link не смог отправить команду")

    async def _step_wait_radio(self, step: dict, store: dict) -> None:
        store_as = step.get("store_as")

        if self.radio_link is None:
            logger.debug(
                "[STUB] wait_radio CMD=%d → пропускаем (нет radio_link)",
                step["expected_cmd"],
            )
            if store_as:
                store[store_as] = b""
            return

        result = await execute_wait_radio(
            step, self.radio_link, self.udp_tx, self.hardware_cfg
        )
        if store_as:
            store[store_as] = result

    async def _step_send_server(self, step: dict, store: dict) -> None:
        cmd         = step["cmd"]
        data_source = step.get("data_source")
        data        = b""

        if isinstance(data_source, dict):
            shutters = data_source.get("shutters")
            data     = struct.pack("bb", int(shutters), 0) if shutters is not None \
                       else bytes(int(v) for v in data_source.values())

        elif isinstance(data_source, str) and data_source.startswith("stored:"):
            keys  = data_source.split(":", 1)[1].split(",")
            parts = [
                serialize_store_value(store[k.strip()])
                for k in keys if k.strip() in store
            ]
            data = b"".join(parts)

        await self.udp_tx.send_packet(cmd=cmd, data=data)
        logger.debug("Серверу CMD=%d (%d байт)", cmd, len(data))

    async def _step_sub_scenario(
        self,
        step:           dict,
        store:          dict,
        parent_name:    str,
        scenario_input: Optional[bytes],
    ) -> None:
        """Встроенный сценарий — выполняется рекурсивно с тем же store."""
        sub_name     = step["name"]
        sub_scenario = self._scenarios.get(sub_name)
        if sub_scenario is None:
            raise RuntimeError(f"Под-сценарий '{sub_name}' не найден")

        sub_abort = sub_scenario.get("abort_on_error", True)
        for sub_step in sub_scenario.get("steps", []):
            try:
                await self._dispatch_step(sub_step, store, sub_name, scenario_input)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("[%s > %s] Ошибка: %s", parent_name, sub_name, exc)
                if sub_abort:
                    raise

    @staticmethod
    def _extract_error_code(message: str) -> str:
        """Вытащить [КОД] из строки вида '[КОД] текст'."""
        if message.startswith("[") and "]" in message:
            return message[1 : message.index("]")]
        return "MECHANICS"

    # ------------------------------------------------------------------
    # Хендлеры — сценарные (кладут задачу в очередь)
    # ------------------------------------------------------------------

    async def handle_open_droneport(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_open_droneport, packet)

    async def _run_open_droneport(self, packet):
        await self._run_scenario_steps("OPEN_DRONEPORT", packet)

    async def handle_close_droneport(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_close_droneport, packet)

    async def _run_close_droneport(self, packet):
        await self._run_scenario_steps("CLOSE_DRONEPORT", packet)

    async def handle_diagnostic(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_diagnostic, packet)

    async def _run_diagnostic(self, packet):
        await self._run_scenario_steps("DIAGNOSTIC", packet)

    async def handle_demo_mode(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_demo_mode, packet)

    async def _run_demo_mode(self, packet):
        await self._run_scenario_steps("DEMO_MODE", packet, scenario_input=packet.data)

    async def handle_combat_mode(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_combat_mode, packet)

    async def _run_combat_mode(self, packet):
        await self._run_scenario_steps("COMBAT_MODE", packet, scenario_input=packet.data)

    async def handle_target_interception(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_target_interception, packet)

    async def _run_target_interception(self, packet):
        await self._run_scenario_steps("TARGET_INTERCEPTION", packet, scenario_input=packet.data)

    async def handle_sector_search(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_sector_search, packet)

    async def _run_sector_search(self, packet):
        await self._run_scenario_steps("SECTOR_SEARCH", packet, scenario_input=packet.data)

    async def handle_diagnostic_flight(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_diagnostic_flight, packet)

    async def _run_diagnostic_flight(self, packet):
        await self._run_scenario_steps("DIAGNOSTIC_FLIGHT", packet)

    async def handle_drone_flight(self, packet):
        if not packet.data or packet.data[0] != self.droneport_id:
            logger.warning(
                "DRONE_FLIGHT: num_src=%s != собственный id=%d",
                packet.data[0] if packet.data else "?", self.droneport_id,
            )
            await self.udp_tx.send_ack(original_cmd=packet.cmd, success=False, error_code=3)
            return
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_drone_flight, packet)

    async def _run_drone_flight(self, packet):
        await self._run_scenario_steps("DRONE_FLIGHT", packet, scenario_input=packet.data)

    async def handle_pre_flight(self, packet):
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._enqueue(self._run_pre_flight, packet)

    async def _run_pre_flight(self, packet):
        await self._run_scenario_steps("PRE_FLIGHT", packet)

    # ------------------------------------------------------------------
    # Хендлеры — запрос/ответ (выполняются немедленно, не через очередь)
    # ------------------------------------------------------------------

    async def handle_status(self, packet):
        """CMD=8. Всегда отвечаем немедленно."""
        busy = not self._queue.empty()
        await self.udp_tx.send_status_droneport(ready=not busy)
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)

    async def handle_condition_dron(self, packet):
        """CMD=4. Состояние дрона: Холл + АКБ → CMD=32."""
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        try:
            hall    = await self.uart_stm32.read_hall_sensors() if self.uart_stm32 else 0b01001010
            voltage = await self.uart_stm32.read_voltage()      if self.uart_stm32 else 12.6

            cell_occupied = (hall >> 6) & 1
            capacity_pct  = max(0, min(100, int((voltage - 10.0) / (13.6 - 10.0) * 100)))

            data = struct.pack(
                "<BBHHBx",
                cell_occupied, 0, int(voltage * 10), capacity_pct, cell_occupied,
            )
            await self.udp_tx.send_packet(cmd=32, data=data)

        except Exception as exc:
            logger.exception("CONDITION_DRON: ошибка")
            await self.error_handler.report_error(
                code="DRONE_NO_RESPONSE", message=str(exc), severity=Severity.WARNING
            )

    async def handle_external_param(self, packet):
        """CMD=5. STM32 DHT22 (temp_in) + Arduino метеостанция (temp_out, wind) → CMD=33."""
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        try:
            # Внутренняя температура — STM32 DHT22
            dht22 = (await self.uart_stm32.read_dht22() if self.uart_stm32
                     else (22.5, 45.0))
            temp_in = int(dht22[0] * 10)  # int16, °C × 10

            # Наружные данные — Arduino метеостанция
            if self.weather_station:
                weather = await self.weather_station.read_weather()
            else:
                weather = None

            if weather:
                temp_out  = int(weather["temperature"] * 10)    # °C × 10 → int16
                wind_spd  = weather["wind_speed"] // 10         # м/с×10 → м/с целое
                wind_spd  = min(wind_spd, 255)                  # обрезаем до uint8
                wind_dir  = weather["wind_dir"]                 # градусы, int16
            else:
                # заглушка
                temp_out = 50     # 5.0°C
                wind_spd = 3      # 3 м/с
                wind_dir = 180    # юг

            data = struct.pack(
                "<hhBhB",
                temp_in,
                temp_out,
                wind_spd,
                wind_dir,
                0,  # reserved
            )
            await self.udp_tx.send_packet(cmd=33, data=data)

        except Exception as exc:
            logger.exception("EXTERNAL_PARAM: ошибка")
            await self.error_handler.report_error(
                code="TEMP_SENSOR_FAIL", message=str(exc), severity=Severity.WARNING
            )

    async def handle_request_coordinate(self, packet):
        """CMD=6. Координаты GPS → CMD=34."""
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        try:
            coords = (await self.usb_sensors.get_coordinates() if self.usb_sensors
                      else {"latitude": 55.751244, "longitude": 37.618423, "altitude": 156.0})

            data = struct.pack(
                "<iii",
                int(coords.get("latitude",  0) * 1e7),
                int(coords.get("longitude", 0) * 1e7),
                int(coords.get("altitude",  0) * 100),
            )
            await self.udp_tx.send_packet(cmd=34, data=data)

        except Exception as exc:
            logger.exception("REQUEST_COORDINATE: ошибка GPS")
            await self.error_handler.report_error(
                code="POSITION_LOST", message=str(exc), severity=Severity.WARNING
            )
            await self.udp_tx.send_packet(cmd=34, data=struct.pack("<iii", 0, 0, 0))

    async def handle_status_shutters(self, packet):
        """CMD=7. Положение крыши через Холл → CMD=30."""
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        try:
            hall        = await self.uart_stm32.read_hall_sensors() if self.uart_stm32 else 0b01001010
            roof_open   = (hall >> 0) & 1
            roof_closed = (hall >> 1) & 1

            if roof_open:
                status = 1
            elif roof_closed:
                status = 0
            else:
                status = -1  # промежуточное положение

            await self.udp_tx.send_packet(cmd=30, data=struct.pack("bb", status, 0))

        except Exception as exc:
            logger.exception("STATUS_SHUTTERS: ошибка")
            await self.error_handler.report_error(
                code="SHUTTER_TIMEOUT", message=str(exc), severity=Severity.ERROR
            )
            await self.udp_tx.send_packet(cmd=30, data=struct.pack("bb", -1, 0))

    # ------------------------------------------------------------------
    # Приоритетные команды (без очереди, выполняются немедленно)
    # ------------------------------------------------------------------

    async def handle_stop(self, packet):
        """
        CMD=26 STOP. Приоритет: наивысший.
        ACK → сброс очереди → STOP БПЛА. Механика остаётся как есть.
        """
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._clear_queue()

        if self.radio_link:
            try:
                await self.radio_link.send_command(cmd=26, data=b"")
            except Exception as exc:
                logger.error("STOP: не смогли отправить команду БПЛА: %s", exc)

        logger.info("STOP: очередь очищена, БПЛА получил STOP")

    async def handle_return(self, packet):
        """
        CMD=27 RETURN. Приоритет: наивысший.
        ACK → сброс очереди → RETURN БПЛА → ждать посадку → закрыть.
        """
        await self.udp_tx.send_ack(original_cmd=packet.cmd, success=True)
        self._clear_queue()

        if self.radio_link:
            try:
                await self.radio_link.send_command(cmd=27, data=b"")
            except Exception as exc:
                logger.error("RETURN: не смогли отправить команду БПЛА: %s", exc)

        self._enqueue(self._run_return_receive, packet)
        logger.info("RETURN: очередь очищена, БПЛА летит домой")

    async def _run_return_receive(self, packet):
        """Открыть дронпорт если закрыт → ждать BOARDING_REQUEST → закрыть."""
        try:
            hall        = await self.uart_stm32.read_hall_sensors() if self.uart_stm32 else 0b01001010
            roof_closed = (hall >> 1) & 1
            if roof_closed:
                logger.info("RETURN: дронпорт закрыт, открываем")
                await self._run_scenario_steps("OPEN_DRONEPORT", packet)

            timeout_sec = float(
                self.hardware_cfg.get("radio_timeouts", {}).get("return_receive", 20.0)
            )
            logger.info("RETURN: ждём BOARDING_REQUEST (таймаут %.0fс)", timeout_sec)

            deadline = asyncio.get_event_loop().time() + timeout_sec
            boarded  = False

            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                if self.radio_link is None:
                    logger.debug("[STUB] RETURN: нет radio_link, пропускаем ожидание")
                    boarded = True
                    break
                try:
                    radio_cmd, _ = await asyncio.wait_for(
                        self.radio_link.receive_packet(), timeout=remaining
                    )
                    if radio_cmd == 44:  # BOARDING_REQUEST
                        boarded = True
                        break
                except asyncio.TimeoutError:
                    break

            if not boarded:
                logger.error("RETURN: БПЛА не запросил посадку за %.0fс", timeout_sec)
                await self.error_handler.report_error(
                    code="DRONE_NO_RESPONSE",
                    message="Нет BOARDING_REQUEST после RETURN",
                    severity=Severity.ERROR,
                )
                return

            logger.info("RETURN: BOARDING_REQUEST получен, закрываем дронпорт")
            await self._run_scenario_steps("CLOSE_DRONEPORT", packet)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("RETURN: ошибка при приёме БПЛА: %s", exc)

    async def handle_drone_comm_status(self, packet):
        """CMD=50. Сервер уведомляет о начале/завершении общения с дроном."""
        status = packet.data[0] if packet.data else 0
        logger.info("Сервер %s общение с дроном", "начал" if status == 1 else "завершил")

    async def handle_coordinate_ned(self, packet):
        """CMD=29. NED @ 200 Гц — прямая ретрансляция без ACK и очереди."""
        if self.radio_link:
            try:
                await self.radio_link.send_command(cmd=29, data=packet.data)
            except Exception as exc:
                logger.debug("COORDINATE_NED: ошибка ретрансляции: %s", exc)