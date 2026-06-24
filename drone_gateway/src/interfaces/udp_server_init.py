"""UDP сокет: создание, привязка, отправка."""
import asyncio
import logging
import socket as _socket
from typing import Optional, Tuple, Callable
from dataclasses import dataclass

from ..encrypt.encryption import load_aesgcm, encrypt_packet, decrypt_packet


@dataclass
class UDPConfig:
    """Конфигурация UDP соединения."""
    bind_ip: str = "0.0.0.0"
    bind_port: int = 5001
    server_ip: Optional[str] = None
    server_port: int = 5000
    receive_timeout: float = 1.0
    send_timeout: float = 2.0


class UDPInitializer:
    """
    Инициализатор UDP соединения. Создаёт сокет ОДИН раз при первом start().
    Повторные вызовы start() ничего не делают — просто возвращают True.
    Это защищает от WinError 10048 (порт занят) при повторной инициализации.
    """

    def __init__(self, logger: logging.Logger, config: UDPConfig):
        self.logger = logger
        self.config = config
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol = None
        self._running = False
        self._receive_callback: Optional[Callable] = None
        self._aesgcm = load_aesgcm()
        self.logger.info(
            f"UDPInitializer created: bind={config.bind_ip}:{config.bind_port}, "
            f"server={config.server_ip}:{config.server_port}"
        )

    def set_receive_callback(self, callback: Callable[[bytes, Tuple[str, int]], None]):
        """Устанавливает callback для обработки полученных пакетов."""
        self._receive_callback = callback
        self.logger.debug("Receive callback set for UDPInitializer")

    async def start(self) -> bool:
        """
        Создаёт UDP сокет и привязывает к порту.

        Если сокет уже создан (повторный вызов) — ничего не делает, возвращает True.
        Это ключевое отличие от старой версии: никаких повторных bind() на один порт.

        Как работает на пальцах:
            Первый вызов: создаём сокет, вешаем на порт, запоминаем transport.
            Второй вызов: видим что transport уже есть — говорим "окей, всё готово" и уходим.
        """
        # Защита от повторного запуска — главное исправление
        if self._transport is not None:
            self.logger.debug("UDP socket already initialized, skipping")
            return True

        try:
            # Создаём сокет вручную чтобы выставить SO_REUSEADDR до bind().
            # Это позволяет переиспользовать порт после краша предыдущего процесса.
            sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            sock.bind((self.config.bind_ip, self.config.bind_port))

            parent = self  # захватываем self для вложенного класса

            class UDPProtocol(asyncio.DatagramProtocol):
                def datagram_received(self, data, addr):
                    try:
                        data = decrypt_packet(parent._aesgcm, data)
                    except Exception as e:
                        parent.logger.warning(f"AES decrypt failed from {addr}: {e}")
                        return
                    if parent._receive_callback:
                        parent._receive_callback(data, addr)

                def connection_lost(self, exc):
                    if exc:
                        parent.logger.error(f"UDP connection lost: {exc}")
                    parent._running = False

            self._transport, self._protocol = (
                await asyncio.get_running_loop().create_datagram_endpoint(
                    lambda: UDPProtocol(),
                    sock=sock  # передаём уже готовый сокет — повторного bind() нет
                )
            )
            self._running = True
            self.logger.info(
                f"UDP socket bound to {self.config.bind_ip}:{self.config.bind_port}"
            )
            return True

        except OSError as e:
            # Отдельная обработка OS-ошибок с понятным сообщением
            if e.winerror == 10048 if hasattr(e, 'winerror') else False:
                self.logger.error(
                    f"Порт {self.config.bind_port} уже занят другим процессом. "
                    f"Выполни: netstat -ano | findstr :{self.config.bind_port} "
                    f"и убей процесс через taskkill /PID <номер> /F"
                )
            elif e.winerror == 10013 if hasattr(e, 'winerror') else False:
                self.logger.error(
                    f"Доступ к порту {self.config.bind_port} запрещён. "
                    f"Возможные причины: антивирус/файрвол блокирует порт, "
                    f"или порт занят системным процессом. "
                    f"Проверь: netstat -ano | findstr :{self.config.bind_port}"
                )
            else:
                self.logger.error(f"Failed to bind UDP socket: {e}", exc_info=True)
            return False

        except Exception as e:
            self.logger.error(f"Failed to initialize UDP socket: {e}", exc_info=True)
            return False

    async def send_raw(self, data: bytes, addr: Optional[Tuple[str, int]] = None) -> bool:
        """Отправляет сырые байты через UDP сокет."""
        if not self._transport:
            self.logger.error("Cannot send: UDP socket not initialized")
            return False
        try:
            target_addr = addr or (self.config.server_ip, self.config.server_port)
            if not target_addr or not target_addr[0]:
                self.logger.error("No target address for sending")
                return False
            encrypted = encrypt_packet(self._aesgcm, data)
            self._transport.sendto(encrypted, target_addr)
            self.logger.debug(
                f"Sent {len(data)}→{len(encrypted)} bytes to {target_addr[0]}:{target_addr[1]}"
            )
            return True
        except Exception as e:
            self.logger.error(f"UDP send error: {e}", exc_info=True)
            return False

    async def stop(self):
        """Корректная остановка UDP соединения."""
        self.logger.info("UDPInitializer stopping...")
        self._running = False
        if self._transport:
            self._transport.close()
            self._transport = None
            self._protocol = None
        self.logger.debug("UDP socket closed")
        await asyncio.sleep(0.1)

    @property
    def is_running(self) -> bool:
        """Проверка состояния сокета."""
        return self._running and self._transport is not None

    @property
    def transport(self) -> Optional[asyncio.DatagramTransport]:
        """Прямой доступ к транспорту."""
        return self._transport