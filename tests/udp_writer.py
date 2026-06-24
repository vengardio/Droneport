#!/usr/bin/env python3
"""
udp_writer.py - Конструктор и отправитель UDP пакетов (Эмулятор Сервера)
Используется для тестирования модуля src/interfaces/udp_server_rx.py
"""
import socket
import struct
import yaml
import os
import sys
from typing import Optional, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from encrypt.encryption import load_aesgcm, encrypt_packet

# ============================================================================
# КОНФИГУРАЦИЯ ПРОТОКОЛА (Совпадает с udp_server_rx.py / udp_server_tx.py)
# ============================================================================
DLE, STX, ETX = 0x10, 0x02, 0x03
SUBSYSTEM_ID = 2001  # ID подсистемы дронпорта
DEFAULT_DRONEPORT_NUM = 1

# Команды СЕРВЕР -> ДРОНПОРТ (из ServerCommand в udp_server_rx.py)
SERVER_COMMANDS = {
    1: "OPEN_DRONPORT", 2: "CLOSE_DRONPORT", 3: "DIAGNOSTIC",
    4: "CONDITION_DRON", 5: "EXTERNAL_PARAM", 6: "REQUEST_COORDINATE",
    7: "STATUS_SHUTTERS", 8: "STATUS", 20: "COMBAT_MODE",
    21: "TARGET_INTERCEPTION", 22: "DEMO_MODE", 23: "SECTOR_SEARCH",
    24: "DIAGNOSTIC_FLIGHT", 25: "DRONE_FLIGHT", 26: "STOP",
    27: "RETURN", 28: "PRE_FLIGHT", 29: "COORDINATE_NED",
    0xF1: "ACK", 0xF2: "NACK"
}

class PacketBuilder:
    """Сборщик пакетов согласно спецификации Таблицы 1"""
    
    @staticmethod
    def calculate_checksum(data: bytes) -> int:
        return sum(data) & 0xFF

    @staticmethod
    def build(subsystem_id: int, droneport_num: int, cmd: int, data: bytes = b'') -> bytes:
        if len(data) > 71:
            raise ValueError("Data length exceeds protocol limit (71 bytes)")
        
        # Формат: <HBBH (ID, Num, Len, Cmd)
        header = struct.pack('<HBBH', subsystem_id, droneport_num, len(data), cmd)
        
        core = header + data
        checksum = PacketBuilder.calculate_checksum(core)
        packet = bytes([DLE, STX]) + core + bytes([checksum, DLE, ETX])
        return packet

class UDPWriter:
    def __init__(self):
        #self.target_ip = "192.168.98.1"
        self.target_ip = "127.0.0.1"
        self.target_port = 7003
        self.droneport_num = DEFAULT_DRONEPORT_NUM
        self.subsystem_id = SUBSYSTEM_ID
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_packet = b''
        self._aesgcm = load_aesgcm()
        print("🔐 AES-256-GCM шифрование активно")

        # Попытка загрузить конфиг для удобства
        self._load_config()

    def _load_config(self):
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'config', 'network.yaml')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f)
                    # Для тестов часто нужно отправлять НА дронпорт (bind_port), 
                    # а не НА сервер (server.port). В network.yaml bind_port = 5001
                    local_cfg = cfg.get('local', {})
                    self.target_port = local_cfg.get('bind_port', 5001)
                    self.droneport_num = cfg.get('droneport', {}).get('id', 1)
                    self.subsystem_id = cfg.get('droneport', {}).get('subsystem_id', 2001)
                    print(f"✅ Конфиг загружен: {self.target_ip}:{self.target_port}")
        except Exception as e:
            print(f"⚠️  Конфиг не загружен, используются значения по умолчанию: {e}")

    def _hex_input(self, prompt: str) -> bytes:
        while True:
            user_input = input(prompt).strip()
            if not user_input:
                return b''
            try:
                # Удаляем пробелы и 0x
                clean = user_input.replace(' ', '').replace('0x', '').replace(',', '')
                if len(clean) % 2 != 0:
                    print("❌ Ошибка: Нечетное количество hex символов")
                    continue
                return bytes.fromhex(clean)
            except ValueError:
                print("❌ Ошибка: Неверный формат HEX (используйте 01 A1 FF)")

    def _print_hex(self, data: bytes, label: str = "Packet"):
        print(f"\n--- {label} ({len(data)} bytes) ---")
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"  {i:04X}: {hex_part:<{16*3}} | {ascii_part}")
        print("-" * 40)

    def send_packet(self, packet: bytes):
        try:
            encrypted = encrypt_packet(self._aesgcm, packet)
            self.sock.sendto(encrypted, (self.target_ip, self.target_port))
            print(f"🚀 Отправлено на {self.target_ip}:{self.target_port} "
                  f"({len(packet)} → {len(encrypted)} байт, зашифровано)")
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")

    def menu_loop(self):
        print("\n🛠  UDP PACKET CONSTRUCTOR (DronePort Server Emulator)")
        print("=" * 60)
        
        while True:
            print(f"\nНастройки: IP={self.target_ip} Port={self.target_port} DP_ID={self.droneport_num}")
            print("1. Выбрать команду")
            print("2. Изменить целевой порт")
            print("3. Изменить ID дронпорта")
            print("4. Отправить последний пакет повторно")
            print("0. Выход")
            
            choice = input("\nВыбор > ").strip()
            
            if choice == '0':
                break
            
            if choice == '1':
                # Выбор команды
                print("\nДоступные команды:")
                sorted_cmds = sorted(SERVER_COMMANDS.items())
                for i, (cmd, name) in enumerate(sorted_cmds):
                    print(f"  {i+1}. CMD {cmd} ({name})")
                
                cmd_idx = input("Номер команды > ").strip()
                try:
                    cmd_val = sorted_cmds[int(cmd_idx)-1][0]
                    cmd_name = sorted_cmds[int(cmd_idx)-1][1]
                except (IndexError, ValueError):
                    print("❌ Неверный выбор")
                    continue

                # Ввод данных
                print(f"\nВведите данные payload в HEX для команды {cmd_name} (Enter для пустых):")
                data = self._hex_input("Data > ")
                
                # Сборка
                try:
                    packet = PacketBuilder.build(self.subsystem_id, self.droneport_num, cmd_val, data)
                    self.last_packet = packet
                    self._print_hex(packet, "Готовый пакет")
                    
                    send = input("Отправить? (y/n) > ").strip().lower()
                    if send == 'y':
                        self.send_packet(packet)
                except Exception as e:
                    print(f"❌ Ошибка сборки пакета: {e}")

            elif choice == '2':
                p = input(f"Новый порт (текущий {self.target_port}) > ").strip()
                if p.isdigit(): self.target_port = int(p)
            
            elif choice == '3':
                d = input(f"Новый ID дронпорта (текущий {self.droneport_num}) > ").strip()
                if d.isdigit(): self.droneport_num = int(d)

            elif choice == '4':
                if self.last_packet:
                    self.send_packet(self.last_packet)
                else:
                    print("❌ Нет последнего пакета")

        self.sock.close()
        print("👋 Завершение работы")

if __name__ == "__main__":
    try:
        writer = UDPWriter()
        writer.menu_loop()
    except KeyboardInterrupt:
        print("\n⚠️  Прервано")