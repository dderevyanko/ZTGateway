#!/usr/bin/env python3
import socket
from .dhcp import parse_dhcp_packet

# DHCP message type names
DHCP_MSG_NAMES = {
    1: "DHCPDISCOVER",
    2: "DHCPOFFER",
    3: "DHCPREQUEST",
    4: "DHCPDECLINE",
    5: "DHCPACK",
    6: "DHCPNAK",
    7: "DHCPRELEASE",
    8: "DHCPINFORM"
}

def main():
    print("ZTGateway – first step: listening for DHCP")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", 67))

    while True:
        data, client = sock.recvfrom(1024)
        mac, msg_type, hostname = parse_dhcp_packet(data)
        
        if mac is not None and msg_type is not None:
            msg_name = DHCP_MSG_NAMES.get(msg_type, f"UNKNOWN({msg_type})")
            if hostname:
                print(f"Received packet from {mac}, type={msg_name}, hostname={hostname}")
            else:
                print(f"Received packet from {mac}, type={msg_name}")
        else:
            print("Received unparsable packet")

if __name__ == "__main__":
    main()