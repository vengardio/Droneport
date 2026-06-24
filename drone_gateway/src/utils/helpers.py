"""Мелкие хелперы: checksum, hex-конверсия."""

def calculate_checksum(data: bytes, checksum_index: int = -1) -> int:
    """Вычисляет контрольную сумму пакета данных (XOR checksum)."""
    if not data: return 0
    if checksum_index < 0: checksum_index = len(data) + checksum_index
    if not (0 <= checksum_index < len(data)):
        raise ValueError(f"Invalid checksum_index {checksum_index} for data length {len(data)}")
    checksum = 0
    for i, byte in enumerate(data):
        if i != checksum_index: checksum ^= byte
    return checksum & 0xFF

def bytes_to_hex(data: int) -> str:
    """Преобразует десятичное целое число в шестнадцатеричную строку."""
    if data < 0: raise ValueError("Negative values are not supported")
    hex_value = f"{data:X}"
    if len(hex_value) % 2 != 0: hex_value = "0" + hex_value
    return f"0x{hex_value}"