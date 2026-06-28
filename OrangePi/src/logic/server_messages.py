"""
Обработка команд от сервера.
Стиль: logic_cyclops.c — switch по cmd, каждая команда = отдельная функция.
"""

import logging
import struct
import time
from typing import Optional

from interfaces.server_rx import DronePortPacket, ServerCommand

log = logging.getLogger("logic")

MAX_HALL_RETRIES = 3

# Контекст — заполняется через Init() из main.py
_stm32         = None
_drone_tx      = None
_server_tx     = None
_drone_q       = None
_gps           = None
_weather       = None
_error_handler = None
_cfg: dict     = {}
_droneport_num = 1


# =============================================================================
#                               INIT
# =============================================================================

def Init(stm32, drone_tx, server_tx, drone_q, gps, weather, error_handler, cfg, droneport_num):
    global _stm32, _drone_tx, _server_tx, _drone_q
    global _gps, _weather, _error_handler, _cfg, _droneport_num
    _stm32         = stm32
    _drone_tx      = drone_tx
    _server_tx     = server_tx
    _drone_q       = drone_q
    _gps           = gps
    _weather       = weather
    _error_handler = error_handler
    _cfg           = cfg
    _droneport_num = droneport_num


# =============================================================================
#                         ГЛАВНЫЙ ДИСПЕТЧЕР
# =============================================================================

def Process(pkt: DronePortPacket):
    cmd = pkt.cmd
    log.info("CMD=%d (%s)", cmd, pkt.cmd_name)

    if   cmd == ServerCommand.OPEN_DRONPORT:        Handle_OpenDroneport(pkt)
    elif cmd == ServerCommand.CLOSE_DRONPORT:       Handle_CloseDroneport(pkt)
    elif cmd == ServerCommand.DIAGNOSTIC:           Handle_Diagnostic(pkt)
    elif cmd == ServerCommand.CONDITION_DRON:       Handle_ConditionDron(pkt)
    elif cmd == ServerCommand.EXTERNAL_PARAM:       Handle_ExternalParam(pkt)
    elif cmd == ServerCommand.REQUEST_COORDINATE:   Handle_RequestCoordinate(pkt)
    elif cmd == ServerCommand.STATUS_SHUTTERS:      Handle_StatusShutters(pkt)
    elif cmd == ServerCommand.STATUS:               Handle_Status(pkt)
    elif cmd == ServerCommand.STOP:                 Handle_Stop(pkt)
    elif cmd == ServerCommand.RETURN:               Handle_Return(pkt)
    elif cmd == ServerCommand.PRE_FLIGHT:           Handle_PreFlight(pkt)
    elif cmd == ServerCommand.COMBAT_MODE:          Handle_CombatMode(pkt)
    elif cmd == ServerCommand.TARGET_INTERCEPTION:  Handle_TargetInterception(pkt)
    elif cmd == ServerCommand.DEMO_MODE:            Handle_DemoMode(pkt)
    elif cmd == ServerCommand.SECTOR_SEARCH:        Handle_SectorSearch(pkt)
    elif cmd == ServerCommand.DIAGNOSTIC_FLIGHT:    Handle_DiagnosticFlight(pkt)
    elif cmd == ServerCommand.DRONE_FLIGHT:         Handle_DroneFlight(pkt)
    elif cmd == ServerCommand.COORDINATE_NED:       Handle_CoordinateNed(pkt)
    elif cmd == ServerCommand.DRONE_COMM_STATUS:    Handle_DroneCommStatus(pkt)
    else: log.warning("Неизвестная команда CMD=%d", cmd)


# =============================================================================
#                         ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

def WaitDroneCmd(expected_cmd: int, timeout: float, relay: tuple = ()) -> Optional[bytes]:
    """
    Аналог DroneResponseWaitCycle из drone-gun.
    Ждём конкретный CMD из drone_q.
    Пакеты из relay — пересылаем серверу попутно.
    Возвращает payload или None при таймауте.
    """
    deadline   = time.monotonic() + timeout
    relay_cmds = set(relay)

    while time.monotonic() < deadline:
        pkt = _drone_q.pop()

        if pkt is None:
            time.sleep(0.01)
            continue

        if pkt.cmd in relay_cmds:
            _server_tx.send_packet(pkt.cmd, pkt.payload)
            log.debug("Ретрансляция CMD=%d серверу", pkt.cmd)

        if pkt.cmd == expected_cmd:
            log.debug("Получен ожидаемый CMD=%d от дрона", expected_cmd)
            return pkt.payload

    log.error("WaitDroneCmd: таймаут %.0fс, CMD=%d не пришёл", timeout, expected_cmd)
    return None


def ReadHall() -> int:
    if _stm32 is None:
        return 0b01001010   # стаб: крыша закр, стол внизу, лапки сжаты
    return _stm32.read_hall_sensors() or 0


def StmAction(code: int) -> bool:
    if _stm32 is None:
        log.debug("[STUB] STM32 action=%d", code)
        return True
    return _stm32.send_action(code)


def StmActionWithHall(code: int, hall_bit: int, expected: int, error_code: str) -> bool:
    """Отправить команду STM32 и проверить датчик Холла. До MAX_HALL_RETRIES попыток."""
    for attempt in range(1, MAX_HALL_RETRIES + 1):
        if not StmAction(code):
            ReportError(error_code, f"STM32 не принял action={code}")
            return False

        if _stm32 is None:
            return True

        hall   = _stm32.read_hall_sensors()
        actual = (hall >> hall_bit) & 1 if hall is not None else -1

        if actual == expected:
            return True

        log.warning("Холл бит%d=%d (ждём %d), попытка %d/%d", hall_bit, actual, expected, attempt, MAX_HALL_RETRIES)

    ReportError(error_code, f"Холл бит{hall_bit} не встал после {MAX_HALL_RETRIES} попыток")
    return False


def ReportError(code: str, msg: str):
    log.error("[%s] %s", code, msg)
    if _error_handler:
        from services.error_handler import Severity
        _error_handler.report_error(code=code, message=msg, severity=Severity.ERROR)


def Timeout(section: str, key: str, default: float = 20.0) -> float:
    return float(_cfg.get(section, {}).get(key, default))


# =============================================================================
#                              СЦЕНАРИИ
# =============================================================================

def Scenario_OpenDroneport() -> bool:
    """Крыша+стол → LED → лапки → сообщить серверу."""
    log.info("[OPEN] Крыша + стол (CMD 22)")
    if not StmActionWithHall(22, 2, 1, "TABLE_TIMEOUT"): return False

    log.info("[OPEN] LED вкл (CMD 7)")
    StmAction(7)

    log.info("[OPEN] Лапки открыть (CMD 15)")
    if not StmActionWithHall(15, 6, 0, "MECHANICS"): return False

    _server_tx.send_packet(cmd=30, data=struct.pack("bb", 1, 0))
    log.info("[OPEN] Готово")
    return True


def Scenario_CloseDroneport() -> bool:
    """Лапки → LED → стол → крыша → сообщить серверу."""
    log.info("[CLOSE] Лапки закрыть (CMD 16)")
    if not StmActionWithHall(16, 6, 1, "MECHANICS"): return False

    log.info("[CLOSE] LED выкл (CMD 8)")
    StmAction(8)

    log.info("[CLOSE] Стол вниз (CMD 14)")
    if not StmActionWithHall(14, 3, 1, "TABLE_TIMEOUT"): return False

    log.info("[CLOSE] Крыша закрыть (CMD 18)")
    if not StmActionWithHall(18, 1, 1, "SHUTTER_TIMEOUT"): return False

    _server_tx.send_packet(cmd=30, data=struct.pack("bb", 0, 0))
    log.info("[CLOSE] Готово")
    return True


def Scenario_PreFlight() -> bool:
    """GPS фикс → проверка Холла → PRE_FLIGHT дрону → ждём DIAG_RESULT."""
    log.info("[PRE_FLIGHT] Ждём GPS фикс")
    gps_timeout = Timeout("sensor_timeouts", "gps_fix", 20.0)
    gps_data = _gps.get_coordinates(gps_timeout) if _gps else {"fix_quality": 1, "latitude": 55.75, "longitude": 37.62, "altitude": 156.0}

    if not gps_data:
        ReportError("POSITION_LOST", f"GPS нет фикса за {gps_timeout:.0f}с")
        return False

    log.info("[PRE_FLIGHT] Проверка Холла (крыша=1, стол=1, лапки=1)")
    hall = ReadHall()
    for bit, expected in [(1, 1), (3, 1), (6, 1)]:
        if (hall >> bit) & 1 != expected:
            ReportError("MECHANICS", f"Исходное положение нарушено: бит Холла {bit}")
            return False

    log.info("[PRE_FLIGHT] Отправляем PRE_FLIGHT дрону (CMD 28)")
    if _drone_tx:
        _drone_tx.send_command(28)
    # DIAG_RESULT дрон отправляет на НавСтанцию напрямую — нам ждать нечего
    log.info("[PRE_FLIGHT] Готово")
    return True


# =============================================================================
#                         ОБРАБОТЧИКИ КОМАНД
# =============================================================================

def Handle_OpenDroneport(pkt):
    #==============================
    #       OPEN DRONEPORT
    # Открыть крышу, поднять стол,
    # включить LED, открыть лапки
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)
    Scenario_OpenDroneport()


def Handle_CloseDroneport(pkt):
    #==============================
    #       CLOSE DRONEPORT
    # Закрыть лапки, выключить LED,
    # опустить стол, закрыть крышу
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)
    Scenario_CloseDroneport()


def Handle_Diagnostic(pkt):
    #==============================
    #         DIAGNOSTIC
    # Собрать данные всех датчиков
    # и отправить серверу (CMD 31, 33)
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    hall    = ReadHall()
    voltage = _stm32.read_voltage()   if _stm32   else 12.6
    dht22   = _stm32.read_dht22()    if _stm32   else (22.5, 45.0)
    weather = _weather.read_weather() if _weather else None

    v_raw = int((voltage or 0) * 10)
    _server_tx.send_packet(cmd=31, data=struct.pack("<BH", hall, v_raw))

    temp_in  = int(dht22[0] * 10) if dht22 else 0
    temp_out = int(weather["temperature"] * 10) if weather else 0
    wind_spd = min(int((weather["wind_speed"] or 0) / 10), 255) if weather else 0
    wind_dir = weather["wind_dir"] if weather else 0
    _server_tx.send_packet(cmd=33, data=struct.pack("<hhBhB", temp_in, temp_out, wind_spd, wind_dir, 0))


def Handle_ConditionDron(pkt):
    #==============================
    #       CONDITION DRON
    # Холл + напряжение → CMD 32
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    hall          = ReadHall()
    voltage       = _stm32.read_voltage() if _stm32 else 12.6
    cell_occupied = (hall >> 6) & 1
    capacity_pct  = max(0, min(100, int(((voltage or 10.0) - 10.0) / 3.6 * 100)))

    _server_tx.send_packet(cmd=32, data=struct.pack(
        "<BBHHBx", cell_occupied, 0, int((voltage or 0) * 10), capacity_pct, cell_occupied
    ))


def Handle_ExternalParam(pkt):
    #==============================
    #       EXTERNAL PARAM
    # DHT22 + метеостанция → CMD 33
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    dht22   = _stm32.read_dht22()    if _stm32   else (22.5, 45.0)
    weather = _weather.read_weather() if _weather else None

    temp_in  = int(dht22[0] * 10) if dht22 else 0
    temp_out = int(weather["temperature"] * 10) if weather else 50
    wind_spd = min(int((weather["wind_speed"] or 0) / 10), 255) if weather else 3
    wind_dir = weather["wind_dir"] if weather else 180

    _server_tx.send_packet(cmd=33, data=struct.pack("<hhBhB", temp_in, temp_out, wind_spd, wind_dir, 0))


def Handle_RequestCoordinate(pkt):
    #==============================
    #     REQUEST COORDINATE
    # GPS → CMD 34
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    pos = _gps.get_coordinates() if _gps else None
    lat = int(pos.get("latitude",  0) * 1e7) if pos else 0
    lon = int(pos.get("longitude", 0) * 1e7) if pos else 0
    alt = int(pos.get("altitude",  0) * 100) if pos else 0

    _server_tx.send_packet(cmd=34, data=struct.pack("<iii", lat, lon, alt))


def Handle_StatusShutters(pkt):
    #==============================
    #      STATUS SHUTTERS
    # Холл → CMD 30 (открыта/закрыта/в движении)
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    hall = ReadHall()
    if   (hall >> 0) & 1: status = 1   # открыта
    elif (hall >> 1) & 1: status = 0   # закрыта
    else:                 status = -1  # в движении

    _server_tx.send_packet(cmd=30, data=struct.pack("bb", status, 0))


def Handle_Status(pkt):
    #==============================
    #           STATUS
    # Ответить готовы/заняты
    #==============================
    _server_tx.send_packet(cmd=35, data=bytes([1]))
    _server_tx.send_ack(pkt.cmd, success=True)


def Handle_Stop(pkt):
    #==============================
    #            STOP
    # Отправить дрону отмену миссии
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)
    if _drone_tx:
        _drone_tx.send_command(26)
    log.info("STOP: дрон получил отмену миссии")


def Handle_Return(pkt):
    #==============================
    #           RETURN
    # Вернуть дрона: CMD 27 → открыть
    # → ждём посадку → закрыть
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    if _drone_tx:
        _drone_tx.send_command(27)

    hall = ReadHall()
    if (hall >> 1) & 1:     # крыша закрыта — открываем
        if not Scenario_OpenDroneport():
            return

    log.info("[RETURN] Ждём BOARDING_REQUEST от дрона (CMD 44)")
    t = Timeout("radio_timeouts", "return_receive", 20.0)
    if WaitDroneCmd(expected_cmd=44, timeout=t) is None:
        ReportError("DRONE_NO_RESPONSE", f"Нет BOARDING_REQUEST после RETURN за {t:.0f}с")
        return

    Scenario_CloseDroneport()


def Handle_PreFlight(pkt):
    #==============================
    #         PRE FLIGHT
    # GPS + Холл + связь с дроном
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)
    Scenario_PreFlight()


def Handle_CombatMode(pkt):
    #==============================
    #        COMBAT MODE
    # PreFlight → Open → CMD 20
    # → ждём посадку → Close
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    if not Scenario_PreFlight():    return
    if not Scenario_OpenDroneport(): return

    if _drone_tx: _drone_tx.send_command(20, pkt.data)

    log.info("[COMBAT] Мониторинг полёта, ждём BOARDING_REQUEST (CMD 44)")
    t = Timeout("radio_timeouts", "boarding_request", 20.0)
    if WaitDroneCmd(44, t, relay=(40, 41, 42)) is None:
        ReportError("DRONE_NO_RESPONSE", "Нет BOARDING_REQUEST в COMBAT_MODE")
        return

    Scenario_CloseDroneport()


def Handle_TargetInterception(pkt):
    #==============================
    #    TARGET INTERCEPTION
    # PreFlight → Open → CMD 21
    # → ждём посадку → Close
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    if not Scenario_PreFlight():    return
    if not Scenario_OpenDroneport(): return

    if _drone_tx: _drone_tx.send_command(21, pkt.data)

    t = Timeout("radio_timeouts", "boarding_request", 20.0)
    if WaitDroneCmd(44, t, relay=(40, 41, 42)) is None:
        ReportError("DRONE_NO_RESPONSE", "Нет BOARDING_REQUEST в TARGET_INTERCEPTION")
        return

    Scenario_CloseDroneport()


def Handle_DemoMode(pkt):
    #==============================
    #         DEMO MODE
    # PreFlight → Open → CMD 22
    # → ждём DEMO_RESULT → ждём посадку → Close
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    if not Scenario_PreFlight():    return
    if not Scenario_OpenDroneport(): return

    if _drone_tx: _drone_tx.send_command(22, pkt.data)

    # DEMO_RESULT дрон шлёт на НавСтанцию напрямую, нам ждать только посадку
    log.info("[DEMO] Ждём BOARDING_REQUEST (CMD 44)")
    t = Timeout("radio_timeouts", "boarding_request", 20.0)
    if WaitDroneCmd(44, t, relay=(40, 41, 42)) is None:
        ReportError("DRONE_NO_RESPONSE", "Нет BOARDING_REQUEST в DEMO_MODE")
        return

    Scenario_CloseDroneport()


def Handle_SectorSearch(pkt):
    #==============================
    #       SECTOR SEARCH
    # PreFlight → Open → CMD 23
    # → ждём посадку → Close
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    if not Scenario_PreFlight():    return
    if not Scenario_OpenDroneport(): return

    if _drone_tx: _drone_tx.send_command(23, pkt.data)

    t = Timeout("radio_timeouts", "boarding_request", 20.0)
    if WaitDroneCmd(44, t, relay=(40, 41, 42)) is None:
        ReportError("DRONE_NO_RESPONSE", "Нет BOARDING_REQUEST в SECTOR_SEARCH")
        return

    Scenario_CloseDroneport()


def Handle_DiagnosticFlight(pkt):
    #==============================
    #     DIAGNOSTIC FLIGHT
    # PreFlight → Open → CMD 24
    # → ждём DIAG_RESULT → ждём посадку → Close
    #==============================
    _server_tx.send_ack(pkt.cmd, success=True)

    if not Scenario_PreFlight():    return
    if not Scenario_OpenDroneport(): return

    if _drone_tx: _drone_tx.send_command(24)

    # DIAG_RESULT дрон шлёт на НавСтанцию напрямую, нам ждать только посадку
    log.info("[DIAG_FLIGHT] Ждём BOARDING_REQUEST (CMD 44)")
    t = Timeout("radio_timeouts", "boarding_request", 20.0)
    if WaitDroneCmd(44, t, relay=(40, 41, 42)) is None:
        ReportError("DRONE_NO_RESPONSE", "Нет BOARDING_REQUEST в DIAGNOSTIC_FLIGHT")
        return

    Scenario_CloseDroneport()


def Handle_DroneFlight(pkt):
    #==============================
    #        DRONE FLIGHT
    # Проверяем что это наш дронпорт,
    # PreFlight → Open → CMD 25 → ждём → Close
    #==============================
    if not pkt.data or pkt.data[0] != _droneport_num:
        log.warning("DRONE_FLIGHT отклонён: num_src=%s, наш=%d", pkt.data[:1].hex() if pkt.data else "?", _droneport_num)
        _server_tx.send_ack(pkt.cmd, success=False, error_code=3)
        return

    _server_tx.send_ack(pkt.cmd, success=True)

    if not Scenario_PreFlight():    return
    if not Scenario_OpenDroneport(): return

    if _drone_tx: _drone_tx.send_command(25, pkt.data)

    t = Timeout("radio_timeouts", "drone_flight", 20.0)
    if WaitDroneCmd(44, t, relay=(40, 41, 42)) is None:
        ReportError("DRONE_NO_RESPONSE", "Нет BOARDING_REQUEST в DRONE_FLIGHT")
        return

    Scenario_CloseDroneport()


def Handle_CoordinateNed(pkt):
    #==============================
    #      COORDINATE NED
    # 200 Гц — прямая трансляция дрону без ACK
    #==============================
    if _drone_tx:
        _drone_tx.send_command(29, pkt.data)


def Handle_DroneCommStatus(pkt):
    #==============================
    #     DRONE COMM STATUS
    # Сервер сообщает начало/конец общения с дроном
    #==============================
    status = pkt.data[0] if pkt.data else 0
    log.info("Сервер %s общение с дроном", "начал" if status == 1 else "завершил")
