"""
Resolve-модуль: парсер команд из текста пользователя.

ТЗ требует: "модуль-парсер, который из входной prompt-строки отбирал бы все
эти команды с их аргументами".

Единственная команда на текущей стадии: \\choose_pkg <pkg_name_or_id>.

Как добавить новую команду:
1. Добавьте регулярное выражение в COMMANDS.
2. Напишите обработчик (например, функцию handle_help).
3. Добавьте обработчик в словарь HANDLERS.
Пример: \\help -> ParsedCommand(command="help", argument=None, clean_text="").
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Callable

logger = logging.getLogger(__name__)


@dataclass
class ParsedCommand:
    """Результат парсинга текста пользователя."""
    command: Optional[str] = None       # например, "choose_pkg"
    argument: Optional[str] = None      # например, "patient_001"
    clean_text: str = ""                # текст без команды (комментарий/вопрос)


# Регулярные выражения для команд
COMMANDS: Dict[str, re.Pattern] = {
    "choose_pkg": re.compile(r"^\s*\\choose_pkg\s+(\S+)\s*(.*)$", re.DOTALL),
}


def parse_command(text: str) -> ParsedCommand:
    """
    Распарсить текст пользователя на команду и комментарий.

    Примеры:
        "\\choose_pkg patient_001" -> ParsedCommand("choose_pkg", "patient_001", "")
        "\\choose_pkg patient_001 Какие аномалии?" -> ParsedCommand("choose_pkg", "patient_001", "Какие аномалии?")
        "Какие аномалии?" -> ParsedCommand(None, None, "Какие аномалии?")

    Args:
        text: входной текст от пользователя.

    Returns:
        ParsedCommand с полями command, argument, clean_text.
    """
    if not text:
        return ParsedCommand(clean_text="")

    for command_name, pattern in COMMANDS.items():
        match = pattern.match(text)
        if match:
            argument = match.group(1)
            clean_text = match.group(2).strip() if match.lastindex and match.lastindex >= 2 else ""
            logger.info(f"🔍 Распознана команда: \\{command_name} {argument}")
            return ParsedCommand(
                command=command_name,
                argument=argument,
                clean_text=clean_text,
            )

    # Команда не найдена — это обычный текст
    return ParsedCommand(clean_text=text.strip())
