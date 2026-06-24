"""
conftest.py — корневая конфигурация pytest для drone_gateway.

Добавляет drone_gateway/ в sys.path (чтобы работали импорты src.*)
и создаёт event loop для каждого теста (нужно для asyncio внутри датаклассов).
"""
import asyncio
import logging
import os
import sys

# Чтобы from src.interfaces.xxx import ... работало из любого теста
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest


@pytest.fixture(autouse=True)
def _event_loop():
    """Event loop на каждый тест — нужен для asyncio.get_event_loop() в DroneTelemetryPacket."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture
def logger():
    """Тихий логгер для тестов — не засоряет вывод."""
    log = logging.getLogger("test")
    log.setLevel(logging.CRITICAL)  # глушим всё кроме критических
    return log
