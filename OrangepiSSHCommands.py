import subprocess
import sys
import os
from pathlib import Path

HOST_DEFAULT = "192.168.98.1"
USER = "orangepi"
PASS = "orangepi"
REMOTE_HOME = "/home/orangepi"
REMOTE_DELETE_DEFAULT = "/home/orangepi/drone_gateway"
LOCAL_FOLDER = Path(r"D:\Home folder\02 Projects\GIT\Droneport\OrangePi")
DEBUG_SCRIPT = "/home/orangepi/OrangePi/tests/uart_send.py"
KEY_PATH = Path.home() / ".ssh" / "id_rsa"


def get_host():
    print(f"\n  1. Стандартный IP: {HOST_DEFAULT}")
    print("  2. Ввести другой")
    c = input("Выбор: ").strip()
    return input("IP: ").strip() if c == "2" else HOST_DEFAULT


def ssh_opts():
    opts = ["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
    if KEY_PATH.exists():
        opts += ["-i", str(KEY_PATH)]
    return opts


def setup_ssh_key(host):
    """Генерирует ключ и копирует на OrangePi через ssh-copy-id или ручной метод"""
    if not KEY_PATH.exists():
        print("\nГенерирую SSH ключ...")
        subprocess.run(["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", str(KEY_PATH), "-N", ""], check=True)
        print("Ключ создан.")

    pub_key = KEY_PATH.with_suffix(".pub").read_text().strip()
    print(f"\nКопирую ключ на {host}... (введи пароль: {PASS})")

    # Добавляем ключ через ssh команду
    cmd = (
        f'ssh -o StrictHostKeyChecking=no {USER}@{host} '
        f'"mkdir -p ~/.ssh && echo {pub_key!r} >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"'
    )
    result = subprocess.run(cmd, shell=True)
    if result.returncode == 0:
        print("SSH ключ установлен. Теперь пароль не нужен.")
    else:
        print("Не удалось скопировать ключ.")


def run_ssh(host, command):
    cmd = ["ssh"] + ssh_opts() + [f"{USER}@{host}", command]
    result = subprocess.run(cmd)
    return result.returncode == 0


def menu_setup_key():
    host = get_host()
    setup_ssh_key(host)


def menu_connect():
    host = get_host()
    print(f"\nПодключаюсь к {USER}@{host}...")
    cmd = ["ssh"] + ["-o", "StrictHostKeyChecking=no"] + [f"{USER}@{host}"]
    if KEY_PATH.exists():
        cmd += ["-i", str(KEY_PATH)]
    subprocess.run(cmd)


def menu_delete():
    host = get_host()
    print(f"\n  1. Стандартный путь: {REMOTE_DELETE_DEFAULT}")
    print("  2. Ввести другой")
    c = input("Выбор: ").strip()
    path = REMOTE_DELETE_DEFAULT if c != "2" else input("Путь: ").strip()
    confirm = input(f"Удалить {path} на {host}? (y/n): ").strip().lower()
    if confirm == "y":
        if run_ssh(host, f"rm -rf {path}"):
            print("Удалено.")
        else:
            print("Ошибка. Ключ не настроен? Запусти пункт 5.")


def menu_upload():
    host = get_host()
    print(f"\n  1. Стандартная папка: {LOCAL_FOLDER}")
    print("  2. Ввести другую")
    c = input("Выбор: ").strip()
    local = LOCAL_FOLDER if c != "2" else Path(input("Путь: ").strip())
    remote = input(f"Куда положить [{REMOTE_HOME}]: ").strip() or REMOTE_HOME

    opts = ["-o", "StrictHostKeyChecking=no", "-r"]
    if KEY_PATH.exists():
        opts += ["-i", str(KEY_PATH)]

    cmd = ["scp"] + opts + [str(local), f"{USER}@{host}:{remote}"]
    print(f"\nКопирую {local} → {USER}@{host}:{remote}")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("Готово.")
    else:
        print("Ошибка. Ключ не настроен? Запусти пункт 5.")


def menu_debug():
    host = get_host()
    print(f"\nЗапускаю {DEBUG_SCRIPT} на {host}...")
    run_ssh(host, f"python3 {DEBUG_SCRIPT}")


def main():
    while True:
        print("\n=== OrangePi SSH ===")
        print("  1. Подключиться (интерактивный shell)")
        print("  2. Удалить папку/файл")
        print("  3. Скопировать папку на OrangePi")
        print("  4. Запустить отладку (uart_send.py)")
        print("  5. Настроить SSH ключ (один раз, потом без пароля)")
        print("  0. Выход")
        choice = input("\nВыбор: ").strip()
        if choice == "1":
            menu_connect()
        elif choice == "2":
            menu_delete()
        elif choice == "3":
            menu_upload()
        elif choice == "4":
            menu_debug()
        elif choice == "5":
            menu_setup_key()
        elif choice == "0":
            break
        else:
            print("Неверный выбор")


if __name__ == "__main__":
    main()
