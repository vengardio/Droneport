#!/usr/bin/env python3
"""
UDP Packet Sniffer для отладки Drone Gateway.
Прослушивает указанный порт и выводит сырые пакеты в HEX.
Согласно протоколу дронпорта (Таблица 1).
"""
import asyncio
import socket
import struct
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
try:
    from encrypt.encryption import load_aesgcm, decrypt_packet
    _aesgcm = load_aesgcm()
    _aes_ok = True
except Exception as e:
    print(f"⚠️  AES не загружен: {e}")
    _aesgcm = None
    _aes_ok = False

# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================
# ✅ ИСПРАВЛЕНО: 0.0.0.0 = слушать все локальные интерфейсы
DEFAULT_LISTEN_IP = "0.0.0.0"  
DEFAULT_LISTEN_PORT = 9006  # Порт СЕРВЕРА (куда дронпорт отправляет данные)
DEFAULT_SERVER_PORT = 7003    # Порт ДРОНПОРТА (куда сервер отправляет команды)

# Константы протокола
DLE = 0x10
STX = 0x02
ETX = 0x03

# Команды (Сервер → Дронпорт)
CMD_SERVER_TO_DRONEPORT = {
    1: "OPEN_DRONPORT", 2: "CLOSE_DRONPORT", 3: "DIAGNOSTIC",
    4: "CONDITION_DRON", 5: "EXTERNAL_PARAM", 6: "REQUEST_COORDINATE",
    7: "STATUS_SHUTTERS", 8: "STATUS", 20: "COMBAT_MODE",
    21: "TARGET_INTERCEPTION", 22: "DEMO_MODE", 23: "SECTOR_SEARCH",
    24: "DIAGNOSTIC_FLIGHT", 25: "DRONE_FLIGHT", 26: "STOP",
    27: "RETURN", 28: "PRE_FLIGHT", 29: "COORDINATE_NED",
    0xF1: "ACK", 0xF2: "NACK"
}

# Команды (Дронпорт → Сервер)
CMD_DRONEPORT_TO_SERVER = {
    30: "RESULT_STATUS_SHUTTERS", 31: "RESULT_DIAGNOSTIC",
    32: "RESULT_CONDITION_DRONE", 33: "RESULT_EXTERNAL_PARAM",
    34: "RESPONSE_COORDINATE_DRONEPORT", 35: "STATUS_DRONEPORT",
    40: "TELEMETRY_FAST", 41: "TELEMETRY_SLOW", 42: "SOS",
    43: "DEMO_RESULT", 44: "BOARDING_REQUEST", 45: "DIAG_RESULT",
    46: "TARGET", 47: "RETURN_DRONE", 48: "ERROR",
    0xF1: "ACK", 0xF2: "NACK"
}

class UDPListener:
    def __init__(self, listen_ip: str, listen_port: int):
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.sock = None
        self.packet_count = 0
    
    def _format_hex(self, data: bytes, width: int = 16) -> str:
        """Форматирует байты в HEX-дамп с ASCII-представлением."""
        if not data:
            return "  [EMPTY DATA]"
        lines = []
        for i in range(0, len(data), width):
            chunk = data[i:i+width]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"  {i:04X}: {hex_part:<{width*3}} | {ascii_part}")
        return "\n".join(lines)
    
    def _calculate_checksum(self, data: bytes) -> int:
        """Вычисляет контрольную сумму: сумма всех байтов mod 256."""
        return sum(data) & 0xFF
    
    def _get_cmd_name(self, cmd: int) -> str:
        """Возвращает имя команды по коду."""
        # Сначала проверяем команды дронпорта (30-48)
        name = CMD_DRONEPORT_TO_SERVER.get(cmd)
        if name:
            return name
        # Затем команды сервера (1-29)
        name = CMD_SERVER_TO_DRONEPORT.get(cmd)
        if name:
            return name
        return f"UNKNOWN({cmd})"
    
    def _parse_packet_structure(self, data: bytes) -> dict:
        """
        Парсит структуру пакета согласно Таблице 1 протокола.
        
        # Структура:
        # [DLE][STX][ID:2][NUM:1][LEN:1][CMD:2][DATA:LEN][CS:1][DLE][ETX]
        
        ⚠️ ВАЖНО: ID занимает 5 байт, но значение хранится в первых 4 байтах.
        5-й байт ID — резерв (всегда 0x00).
        """
        info = {"valid": False, "fields": {}}
        
        # Проверка на пустые данные
        if data is None or len(data) == 0:
            info["error"] = "Data is None or empty"
            return info
        
        # Минимальный размер: DLE+STX(2) + ID(2) + NUM(1) + LEN(1) + CMD(2) + CS(1) + DLE+ETX(2) = 11
        if len(data) < 11:  # было 14
            info["error"] = f"Packet too short ({len(data)} bytes, min 14)"
            return info
        try:
            # ========== ПРОВЕРКА ФРЕЙМИНГА ==========
            if data[0:2] == bytes([DLE, STX]):
                info["fields"]["prefix"] = "DLE+STX ✓"
            else:
                info["fields"]["prefix"] = f"INVALID ({data[0:2].hex()})"
                return info
            
            if data[-2:] == bytes([DLE, ETX]):
                info["fields"]["suffix"] = "DLE+ETX ✓"
            else:
                info["fields"]["suffix"] = f"INVALID ({data[-2:].hex()})"
                return info
            
            # ========== ИЗВЛЕЧЕНИЕ CORE ==========
            # core = всё между префиксом и (checksum + суффикс)
            core = data[2:-3]  # Убираем DLE+STX в начале и CS+DLE+ETX в конце
            checksum = data[-3]
            calc_checksum = self._calculate_checksum(core)
            
            # ========== ПРОВЕРКА КОНТРОЛЬНОЙ СУММЫ ==========
            info["fields"]["checksum"] = f"{checksum:02X} (calc: {calc_checksum:02X})"
            info["fields"]["checksum_valid"] = checksum == calc_checksum
            
            if not info["fields"]["checksum_valid"]:
                info["error"] = "Checksum mismatch!"
                return info
            
            # ========== ПАРСИНГ ПОЛЕЙ (Таблица 1) ==========
            if len(core) < 6:
                info["error"] = "Core too short for header"
                return info

            # === ИЗМЕНЕНИЕ: Распаковка Little Endian ===
            id_val, num, data_len, cmd = struct.unpack('<HBBH', core[0:6])
            
            # Данные (если есть)
            if data_len > 0:
                packet_data = core[6:6+data_len]
            else:
                packet_data = b''
            
            # Проверка соответствия длины
            actual_data_len = len(core) - 6
            if data_len != actual_data_len:
                info["warning"] = f"Data length mismatch: declared={data_len}, actual={actual_data_len}"
            
            # ========== ЗАПОЛНЕНИЕ РЕЗУЛЬТАТА ==========
            info["fields"]["id"] = id_val
            info["fields"]["num"] = num
            info["fields"]["data_len"] = data_len
            info["fields"]["cmd"] = cmd
            info["fields"]["cmd_name"] = self._get_cmd_name(cmd)
            info["fields"]["data"] = packet_data.hex() if packet_data else "(empty)"
            
            # Расшифровка DATA для STATUS_DRONEPORT (CMD=35)
            if cmd == 35 and len(packet_data) >= 1:
                status = packet_data[0]
                if status == 0:
                    info["fields"]["data_decoded"] = "Дронпорт НЕ готов"
                elif status == 1:
                    info["fields"]["data_decoded"] = "Дронпорт ГОТОВ ✓"
                elif status == 255:  # -1 в signed
                    info["fields"]["data_decoded"] = "Ошибка дронпорта"
                else:
                    info["fields"]["data_decoded"] = f"Неизвестный статус: {status}"
            
            info["valid"] = True
            
        except Exception as e:
            info["error"] = f"Parse error: {e}"
            import traceback
            info["error_detail"] = traceback.format_exc()
        
        return info
    
    async def listen(self):
        """Асинхронный цикл прослушивания."""
        loop = asyncio.get_running_loop()
        
        # Создаём UDP сокет
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # ✅ ИСПРАВЛЕНО: Привязываемся к локальному адресу
        try:
            self.sock.bind((self.listen_ip, self.listen_port))
        except OSError as e:
            print(f"\n❌ ОШИБКА BIND: {e}")
            print(f"   Вы пытаетесь привязаться к {self.listen_ip}, но этот IP не существует на данной машине!")
            print(f"   Решение: используйте '0.0.0.0' для всех интерфейсов или ваш локальный IP")
            sys.exit(1)
        
        self.sock.settimeout(1.0)
        
        print(f"\n{'='*70}")
        print(f"📡 UDP LISTENER STARTED (DronePort Protocol)")
        print(f"{'='*70}")
        print(f"Listening on: {self.listen_ip}:{self.listen_port}")
        print(f"Protocol: UDP, DLE/STX/ETX framing")
        print(f"Press Ctrl+C to stop")
        print(f"{'='*70}\n")
        
        while True:
            try:
                data, addr = await loop.sock_recvfrom(self.sock, 4096)
                
                if data is None or len(data) == 0:
                    print(f"\n⚠️  Empty packet from {addr}, skipping...")
                    continue
                
                self.packet_count += 1
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                raw_size = len(data)
                if _aes_ok and _aesgcm:
                    try:
                        data = decrypt_packet(_aesgcm, data)
                        aes_label = f"зашифровано {raw_size}→{len(data)} байт"
                    except Exception as e:
                        aes_label = f"⚠️  расшифровка не удалась: {e}"
                else:
                    aes_label = "AES выключен"

                print(f"\n{'─'*70}")
                print(f"[{timestamp}] Packet #{self.packet_count} from {addr[0]}:{addr[1]}")
                print(f"Size: {len(data)} bytes  [{aes_label}]")
                print(f"{'─'*70}")
                
                # HEX-дамп
                print("\n📦 RAW HEX:")
                print(self._format_hex(data))
                
                # Структура пакета
                print("\n🔍 PACKET STRUCTURE:")
                parsed = self._parse_packet_structure(data)
                
                for key, value in parsed.get("fields", {}).items():
                    print(f"  {key}: {value}")
                
                if "warning" in parsed:
                    print(f"  ⚠️  WARNING: {parsed['warning']}")
                
                if "error" in parsed:
                    print(f"  ❌ ERROR: {parsed['error']}")
                    if "error_detail" in parsed:
                        print(f"  {parsed['error_detail']}")
                
                print(f"{'─'*70}\n")
                
            except asyncio.TimeoutError:
                continue
            except KeyboardInterrupt:
                print("\n🛑 Stopped by user")
                break
            except Exception as e:
                print(f"\n❌ Error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1)
        
        if self.sock:
            self.sock.close()
        
        print(f"\nTotal packets received: {self.packet_count}")


async def main():
    port = DEFAULT_LISTEN_PORT
    ip = DEFAULT_LISTEN_IP
    
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}")
            sys.exit(1)
    
    if len(sys.argv) > 2:
        ip = sys.argv[2]
    
    listener = UDPListener(ip, port)
    await listener.listen()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
