#!/usr/bin/env python3
import socket
from core.dhcp_protocol import parse_dhcp_packet

def main():
    print("ZTGateway – первый шаг: слушаем DHCP")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 67))

    while True:
        data, client = sock.recvfrom(1024)
        mac, msg_type = parse_dhcp_packet(data)
        if mac:
            print(f"Получен пакет от {mac}, тип={msg_type}")
        else:
            print("Получен неразборчивый пакет")

if __name__ == "__main__":
    main()