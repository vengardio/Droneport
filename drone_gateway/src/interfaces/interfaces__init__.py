"""
src/interfaces/__init__.py
Драйверы взаимодействия с железом и сетью.
"""

# UDP: связь с центральным сервером
from .udp_server_init import UDPInitializer, UDPConfig
from .udp_server_rx   import UDPServerRX, ServerCommand, DronePortPacket
from .udp_server_tx   import UDPServerTX, DroneportCommand

# USART: связь с радиопередатчиком БПЛА
from .usart_drone_init import USARTDroneInitializer, USARTConfig, DroneRadioType
from .usart_drone_rx   import USARTDroneRX, DroneTelemetryPacket, DroneProtocolType
from .usart_drone_tx   import USARTDroneTX, DroneCommandType

# UART: связь с микроконтроллером STM32
from .uart_stm32_init import STM32Interface, STM32Transport, STM32PacketError

# TODO: раскомментировать по мере реализации
from .radio_link    import RadioLink, RadioLinkConfig
from .uart_weather  import WeatherStation
# from .usb_sensors import USBSensors

__all__ = [
    # UDP
    "UDPInitializer",
    "UDPConfig",
    "UDPServerRX",
    "UDPServerTX",
    "ServerCommand",
    "DronePortPacket",
    "DroneportCommand",
    # USART
    "USARTDroneInitializer",
    "USARTConfig",
    "DroneRadioType",
    "USARTDroneRX",
    "USARTDroneTX",
    "DroneTelemetryPacket",
    "DroneProtocolType",
    "DroneCommandType",
    # UART
    "STM32Interface",
    "STM32Transport",
    "STM32PacketError",
    "RadioLink",
    "RadioLinkConfig",
    "WeatherStation",
]