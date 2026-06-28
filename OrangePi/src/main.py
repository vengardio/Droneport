import sys
import time
from pathlib import Path

import yaml

from services.logger        import setup_logger
from services.message_queue import server_q, drone_q
from services.error_handler import ErrorHandler
from interfaces.server_rx   import ServerRX
from interfaces.server_tx   import ServerTX
from interfaces.stm32_tx    import STM32Interface
from interfaces.drone_rx    import DroneRX
from interfaces.drone_tx    import DroneTX
from interfaces.gps         import GPS
from interfaces.weather_rx  import WeatherStation
import logic.server_messages as Messages

BASE_DIR = Path(__file__).parent.parent


# =============================================================================
#                              КОНФИГ
# =============================================================================

def LoadConfig() -> dict:
    with open(BASE_DIR / "config" / "hardware.yaml", encoding="utf-8") as f:
        hw = yaml.safe_load(f)
    with open(BASE_DIR / "config" / "network.yaml", encoding="utf-8") as f:
        net = yaml.safe_load(f)

    hw["server"]        = net.get("server", {})
    hw["droneport_num"] = net.get("droneport", {}).get("id", 1)
    hw["subsystem_id"]  = net.get("droneport", {}).get("subsystem_id", 2001)
    hw["bind_ip"]       = net.get("local", {}).get("bind_ip",   "0.0.0.0")
    hw["bind_port"]     = net.get("local", {}).get("bind_port", 7003)
    return hw


# =============================================================================
#                           ИНИЦИАЛИЗАЦИЯ
# =============================================================================

def App_Init(cfg: dict):
    log = setup_logger("main", log_file_path=str(BASE_DIR / "logs" / "gateway.log"))
    log.info("=== Droneport Gateway запуск ===")

    num  = cfg["droneport_num"]
    s_id = cfg["subsystem_id"]

    # ── Железо ──────────────────────────────────────────────────────────────
    stm32   = STM32Interface (cfg["uart_stm32"]["port"],    cfg["uart_stm32"]["baudrate"],    setup_logger("stm32"))
    drone   = DroneRX        (cfg["usart_drone"]["port"],  cfg["usart_drone"]["baudrate"],   drone_q, setup_logger("drone_rx"))
    gps     = GPS            (cfg["gps"]["port"],          cfg["gps"]["baudrate"],            setup_logger("gps"))
    weather = WeatherStation (cfg["weather_station"]["port"], cfg["weather_station"]["baudrate"], setup_logger("weather"))

    stm32.connect()   or log.warning("STM32 недоступен — заглушка")
    drone.start()     or log.warning("Дрон UART недоступен — заглушка")
    gps.connect()     or log.warning("GPS недоступен — заглушка")
    weather.connect() or log.warning("Метеостанция недоступна — заглушка")

    # ── Сеть ────────────────────────────────────────────────────────────────
    rx = ServerRX(cfg["bind_ip"], cfg["bind_port"], server_q, setup_logger("server_rx"), s_id, num)
    rx.start() or (log.error("ServerRX не запустился — выход") or sys.exit(1))

    tx      = ServerTX(cfg["server"]["ip"], cfg["server"]["port"], rx.get_socket(), setup_logger("server_tx"), s_id, num)
    errors  = ErrorHandler(setup_logger("errors"), num, send_callback=lambda cmd, data: tx.send_packet(cmd, data))

    # ── DroneTX использует тот же serial что открыл DroneRX ────────────────
    drone_tx = DroneTX(drone._ser, setup_logger("drone_tx")) if drone.is_connected else None

    # ── Логика ──────────────────────────────────────────────────────────────
    Messages.Init(
        stm32         = stm32   if stm32.is_connected   else None,
        drone_tx      = drone_tx,
        server_tx     = tx,
        drone_q       = drone_q,
        gps           = gps     if gps.is_connected     else None,
        weather       = weather if weather.is_connected  else None,
        error_handler = errors,
        cfg           = cfg,
        droneport_num = num,
    )

    tx.send_packet(cmd=35, data=bytes([1]))
    log.info("Дронпорт №%d готов", num)
    return log, rx



# =============================================================================
#                               СТАРТ
# =============================================================================

if __name__ == "__main__":
    cfg      = LoadConfig()
    log, rx  = App_Init(cfg)
    try:
        while True:
            pkt = server_q.pop()
            if pkt:
                Messages.Process(pkt)   
            time.sleep(0.005)
    except KeyboardInterrupt:   
        log.info("Завершение")
        rx.stop()
        sys.exit(0)
