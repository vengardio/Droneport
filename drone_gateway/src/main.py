#!/usr/bin/env python3
"""main.py - Точка входа в систему DronePort"""
import asyncio
import logging
import os
import sys
import yaml

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, BASE_DIR)

from src.interfaces.udp_server_init import UDPInitializer, UDPConfig
from src.interfaces.udp_server_tx   import UDPServerTX
from src.interfaces.udp_server_rx   import UDPServerRX
from src.services.logger            import setup_logger
from src.services.error_handler     import ErrorHandler, Severity
from src.interfaces.uart_stm32_init import STM32Interface
from src.interfaces.radio_link      import RadioLink, RadioLinkConfig
from src.interfaces.uart_weather    import WeatherStation


async def load_config(config_path: str) -> dict:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Failed to load config: {e}")
        return {}


async def main():
    # ------------------------------------------------------------------
    # 1. Логгер
    # ------------------------------------------------------------------
    log_path = os.path.join(BASE_DIR, "logs", "system.log")
    logger = setup_logger(name="DronePortMain", level=logging.DEBUG, log_file_path=log_path)
    logger.info("=" * 70)
    logger.info("🚁 DronePort System Starting...")
    logger.info("=" * 70)

    # ------------------------------------------------------------------
    # 2. Конфиг
    # ------------------------------------------------------------------
    config = await load_config(os.path.join(BASE_DIR, "config", "network.yaml"))
    if not config:
        logger.error("Config loading failed, exiting...")
        return

    hw_config_path = os.path.join(BASE_DIR, "config", "hardware.yaml")

    HARDWARE_DEFAULTS = {
        "action_timeouts": {
            "open_roof": 15, "close_roof": 15,
            "raise_table": 12, "lower_table": 12,
            "open_clamps": 8, "close_clamps": 8,
            "open_vent": 3, "close_vent": 3,
            "default": 5,
        }
    }

    if os.path.exists(hw_config_path):
        with open(hw_config_path, 'r', encoding='utf-8') as f:
            loaded = yaml.safe_load(f)
        if loaded:
            hardware_cfg = loaded
            logger.info("✅ hardware.yaml загружен")
        else:
            hardware_cfg = HARDWARE_DEFAULTS
            logger.warning("hardware.yaml пустой, используются дефолтные тайминги")
    else:
        hardware_cfg = HARDWARE_DEFAULTS
        logger.warning("hardware.yaml не найден, используются дефолтные тайминги")

    server_ip     = config.get('server',    {}).get('ip',           '127.0.0.1')
    server_port   = config.get('server',    {}).get('port',         5000)
    bind_ip       = config.get('local',     {}).get('bind_ip',      '0.0.0.0')
    bind_port     = config.get('local',     {}).get('bind_port',    5001)
    droneport_id  = config.get('droneport', {}).get('id',           1)
    subsystem_id  = config.get('droneport', {}).get('subsystem_id', 2001)
    log_raw       = config.get('debug',     {}).get('log_raw_packets', True)

    logger.info(f"📍 DronePort ID: {droneport_id}, Subsystem: {subsystem_id}")
    logger.info(f"🌐 Server: {server_ip}:{server_port}")
    logger.info(f"🔌 Bind:   {bind_ip}:{bind_port}")

    # ------------------------------------------------------------------
    # 3. UDP сокет
    # ------------------------------------------------------------------
    udp_cfg = UDPConfig(
        bind_ip=bind_ip,
        bind_port=bind_port,
        server_ip=server_ip,
        server_port=server_port,
    )
    udp_init = UDPInitializer(logger=logger, config=udp_cfg)
    if not await udp_init.start():
        logger.error("❌ Failed to initialize UDP socket")
        return
    logger.info("✅ UDP socket OK")

    # ------------------------------------------------------------------
    # 4. UDP RX / TX
    # ------------------------------------------------------------------
    udp_rx = UDPServerRX(
        logger=logger,
        droneport_num=droneport_id,
        subsystem_id=subsystem_id,
        log_raw=log_raw,
    )
    udp_init.set_receive_callback(udp_rx.on_datagram_received)
    logger.info("✅ UDP RX OK")

    udp_tx = UDPServerTX(
        logger=logger,
        udp_init=udp_init,
        droneport_num=droneport_id,
        subsystem_id=subsystem_id,
        log_raw=log_raw,
    )
    logger.info("✅ UDP TX OK")

    # ------------------------------------------------------------------
    # 5. ErrorHandler
    # ------------------------------------------------------------------
    async def _error_send_cb(cmd: int, data: bytes) -> bool:
        return await udp_tx.send_packet(cmd=cmd, data=data)

    error_handler = ErrorHandler(
        logger=logger,
        droneport_num=droneport_id,
        send_callback=_error_send_cb,
        buffer_errors=True,
    )
    logger.info("✅ ErrorHandler OK")

    # ------------------------------------------------------------------
    # 6. Заглушки для железа (пока не реализованы)
    #    Когда uart_stm32 / radio_link / usb_sensors будут готовы —
    #    просто замени None на реальные объекты.
    # ------------------------------------------------------------------
    uart_stm32 = STM32Interface(
        port=hardware_cfg.get("uart_stm32", {}).get("port", "/dev/ttyS0"),
        baudrate=hardware_cfg.get("uart_stm32", {}).get("baudrate", 115200),
        logger=logger,
    )
    if not await uart_stm32.connect():
        logger.error("❌ Не удалось открыть STM32 UART")
        #return
    await uart_stm32.drain()  # вычистить мусор после старта STM32
    radio_cfg = RadioLinkConfig(
        port=hardware_cfg.get("usart_drone", {}).get("port", "/dev/ttyUSB0"),
        baudrate=hardware_cfg.get("usart_drone", {}).get("baudrate", 115200),
        timeout=0.1,
        log_raw=log_raw,
    )
    radio_link = RadioLink(logger=logger, config=radio_cfg)
    if not await radio_link.start():
        if hardware_cfg.get("stubs", {}).get("radio_link", False):
            logger.warning("⚠️  RadioLink не поднялся — работаем БЕЗ радио (заглушка)")
            radio_link = None
        else:
            logger.error("❌ Не удалось поднять RadioLink")
            return

    usb_sensors = None  # TODO: USBSensors(...)        из usb_sensors.py

    # ------------------------------------------------------------------
    # 6b. Метеостанция (Arduino Nano, UART)
    # ------------------------------------------------------------------
    ws_cfg = hardware_cfg.get("weather_station", {})
    weather_station = WeatherStation(
        port=ws_cfg.get("port", "/dev/ttyUSB1"),
        baudrate=ws_cfg.get("baudrate", 115200),
        timeout=hardware_cfg.get("sensor_timeouts", {}).get("weather", 5),
        logger=logger,
    )
    if await weather_station.connect():
        logger.info("✅ WeatherStation OK")
    else:
        if hardware_cfg.get("stubs", {}).get("weather_station", False):
            logger.warning("⚠️  WeatherStation не поднялась — работаем с заглушкой")
            weather_station = None
        else:
            logger.warning("⚠️  WeatherStation не поднялась — handle_external_param будет использовать заглушку")
            weather_station = None

    # ------------------------------------------------------------------
    # 7. CommandHandlers + воркер очереди
    # ------------------------------------------------------------------
    from src.core.command_handlers import CommandHandlers

    handlers = CommandHandlers(
        udp_tx=udp_tx,
        uart_stm32=uart_stm32,
        radio_link=radio_link,
        usb_sensors=usb_sensors,
        weather_station=weather_station,
        error_handler=error_handler,
        hardware_cfg=hardware_cfg,
        droneport_id=droneport_id,
    )
    handlers.register_all(rx_module=udp_rx)
    worker_task = handlers.start_worker()  # asyncio.Task, уже создан внутри
    logger.info("✅ CommandHandlers OK, worker запущен")
    await udp_tx.send_status_droneport(ready=True)
    
    # --- Включение вибромоторов (антиобледенение) ---
    try:
        ok = await uart_stm32.send_action(1)       # старт вибро (код 1)
        if ok:
            logger.info("Вибромоторы запущены")
            await asyncio.sleep(10)                 # крутим 10 секунд
            ok = await uart_stm32.send_action(2)    # стоп вибро (код 2)
            if ok:
                logger.info("Вибромоторы остановлены")
            else:
                logger.error("NACK на остановку вибро")
        else:
            logger.error("NACK на запуск вибро")
    except Exception as e:
        logger.error("Ошибка управления вибромоторами: %s", e)
    # --- конец вибро ---


    # ------------------------------------------------------------------
    # 8. Ожидание (основной цикл)
    # ------------------------------------------------------------------
    logger.info("=" * 70)
    logger.info("👂 Система в режиме ожидания команд")
    logger.info("💡 Запусти tests/udp_writer.py для отправки команд")
    logger.info("=" * 70)

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass

    # ------------------------------------------------------------------
    # 9. Корректное завершение
    # ------------------------------------------------------------------
    logger.info("🛑 Завершение работы...")

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    await udp_tx.send_status_droneport(ready=False)
    await error_handler.shutdown()
    await radio_link.stop()
    if weather_station:
        await weather_station.disconnect()
    await udp_init.stop()

    logger.info("✅ Система остановлена")
    logger.info("=" * 70)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)