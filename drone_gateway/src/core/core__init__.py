"""
src/core/__init__.py
Ядро системы — бизнес-логика и обработка команд.
"""

from .command_handlers import CommandHandlers

__all__ = [
    "CommandHandlers",
]