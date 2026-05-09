import struct

# DHCP message types
DHCPDISCOVER = 1
DHCPOFFER = 2
DHCPREQUEST = 3
DHCPACK = 5

def parse_dhcp_packet(data: bytes):
    """
    Извлекает MAC-адрес клиента и тип DHCP-сообщения.
    Возвращает (mac, message_type) или (None, None) при ошибке.
    """
    if len(data) < 240:
        return None, None

    # MAC-адрес находится в байтах 28..33
    mac_bytes = data[28:34]
    mac = ":".join(f"{b:02x}" for b in mac_bytes)

    # Ищем DHCP-опции (начинаются с 4-байтового magic cookie 99,130,83,99)
    cookie = struct.unpack("!I", data[236:240])[0]
    if cookie != 0x63825363:
        return None, None

    # Парсим опции, чтобы найти option 53 (DHCP message type)
    idx = 240
    msg_type = None
    while idx < len(data):
        opt = data[idx]
        if opt == 0:          # pad option
            idx += 1
            continue
        if opt == 255:        # end option
            break
        if idx + 1 >= len(data):
            break
        length = data[idx + 1]
        if idx + 2 + length > len(data):
            break
        if opt == 53:         # DHCP message type
            if length >= 1:
                msg_type = data[idx + 2]
                break
        idx += 2 + length

    return mac, msg_type