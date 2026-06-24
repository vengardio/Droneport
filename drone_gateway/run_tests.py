#!/usr/bin/env python3
"""
Запуск всех unit-тестов дронпорта.

Использование:
    python run_tests.py          # все тесты
    python run_tests.py -k stm32 # только тесты с "stm32" в имени
    python run_tests.py -x       # остановиться на первом провале
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    print()
    print("━" * 60)
    print("   DRONEPORT — UNIT TESTS")
    print("━" * 60)
    print()

    extra_args = sys.argv[1:]  # прокидываем доп. аргументы из командной строки

    cmd = [
        sys.executable, "-m", "pytest",
        "tests/unit/",
        "-v",               # имя каждого теста
        "--tb=short",       # компактный traceback при падении
        "--color=yes",      # цвет в терминале
        "-p", "no:warnings",  # без лишнего мусора про warnings
        *extra_args,
    ]

    result = subprocess.run(cmd, cwd=ROOT)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
