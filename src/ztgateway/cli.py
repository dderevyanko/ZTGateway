#!/usr/bin/env python3
"""
ZTGateway CLI - Zero Touch Provisioning Gateway
DHCP server for IP phones provisioning
"""

import argparse
import socket
import sys
from typing import Optional, Tuple
from .dhcp import parse_dhcp_packet

# ---------------------------
# Конфигурация
# ---------------------------
DEFAULT_PORT = 67
DEFAULT_RCVBUF = 262144  # 256KB буфер для высокой нагрузки
DEFAULT_INTERFACE = "all"

# DHCP message type names
DHCP_MSG_NAMES = {
    1: "DHCPDISCOVER",
    2: "DHCPOFFER",
    3: "DHCPREQUEST",
    4: "DHCPDECLINE",
    5: "DHCPACK",
    6: "DHCPNAK",
    7: "DHCPRELEASE",
    8: "DHCPINFORM",
}

# Lazy-импорт netifaces (только по необходимости)
_netifaces = None


def _get_netifaces():
    """Lazy load netifaces module"""
    global _netifaces
    if _netifaces is None:
        try:
            import netifaces
            _netifaces = netifaces
        except ImportError:
            return None
    return _netifaces


def get_interface_ip(interface_name: str) -> Optional[str]:
    """Get IP address of a network interface"""
    netifaces = _get_netifaces()
    if netifaces is None:
        return None
    try:
        addrs = netifaces.ifaddresses(interface_name)
        return addrs[netifaces.AF_INET][0]["addr"]
    except (KeyError, ValueError, IndexError):
        return None


def list_interfaces() -> None:
    """Print available network interfaces"""
    netifaces = _get_netifaces()
    if netifaces is None:
        print("netifaces not installed. Install with: pip install netifaces")
        return
    print("Available network interfaces:")
    for iface in netifaces.interfaces():
        ip = get_interface_ip(iface)
        if ip:
            print(f"  {iface} (IP: {ip})")
        else:
            print(f"  {iface} (no IP)")


def interactive_interface_selection() -> Optional[str]:
    """Interactive selection of network interface"""
    netifaces = _get_netifaces()
    if netifaces is None:
        print("netifaces not installed. Using default 'all'.")
        return DEFAULT_INTERFACE
    
    interfaces = []
    print("\nAvailable network interfaces:")
    for iface in netifaces.interfaces():
        ip = get_interface_ip(iface)
        if ip:
            print(f"  {len(interfaces)+1}) {iface} (IP: {ip})")
            interfaces.append(iface)
        else:
            print(f"  {iface} (no IP) - skipped")
    
    if not interfaces:
        print("No interfaces with IP found. Using 'all'.")
        return DEFAULT_INTERFACE
    
    print(f"  {len(interfaces)+1}) all (listen on all interfaces)")
    print(f"  {len(interfaces)+2}) Exit")
    
    while True:
        try:
            choice = input(f"\nSelect interface (1-{len(interfaces)+2}): ").strip()
            if choice == str(len(interfaces)+2):
                return None
            if choice == str(len(interfaces)+1):
                return DEFAULT_INTERFACE
            idx = int(choice) - 1
            if 0 <= idx < len(interfaces):
                return interfaces[idx]
            print(f"Invalid choice. Enter 1-{len(interfaces)+2}")
        except ValueError:
            print(f"Please enter a number (1-{len(interfaces)+2})")
        except KeyboardInterrupt:
            print("\n")
            return None


def create_socket(interface_name: str, port: int, rcvbuf: int) -> socket.socket:
    """Create and bind socket to specified interface"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Доп. оптимизации
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass  # не поддерживается на macOS/Windows

    if interface_name == "all":
        sock.bind(("", port))
        print(f"Listening on ALL interfaces, port {port}")
    else:
        ip = get_interface_ip(interface_name)
        if not ip:
            raise ValueError(f"Interface {interface_name} has no IP address")
        sock.bind((ip, port))
        print(f"Listening on interface {interface_name} (IP: {ip}), port {port}")
    return sock


def format_packet_info(
    mac: str, msg_type: int, hostname: Optional[str], client: Tuple[str, int]
) -> str:
    """
    Format packet information for logging.
    
    The `client` tuple comes from socket.recvfrom() and contains (source_ip, source_port).
    
    IMPORTANT:
    - DHCPDISCOVER is always sent from 0.0.0.0 (source_ip = '0.0.0.0')
      because the client has no IP address yet.
    - Source port is typically 68 (client DHCP port).
    
    Example: src=('0.0.0.0', 68) means: client has no IP, expects response on port 68.
    
    This is NORMAL behavior for a DHCPDISCOVER packet, NOT an error.
    """
    msg_name = DHCP_MSG_NAMES.get(msg_type, f"UNKNOWN({msg_type})")
    base = f"Received from {mac}, type={msg_name}"
    if hostname:
        base += f", hostname={hostname}"
    return f"{base}, src={client}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ZTGateway – Zero Touch Provisioning Gateway"
    )
    parser.add_argument(
        "-i", "--interface",
        default=None,
        help="Network interface to listen on (e.g., eth0, enx00e04c150bdf, all)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"DHCP port (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--rcvbuf",
        type=int,
        default=DEFAULT_RCVBUF,
        help=f"Socket receive buffer size (default: {DEFAULT_RCVBUF})"
    )
    parser.add_argument(
        "--list-interfaces",
        action="store_true",
        help="Show available network interfaces and exit"
    )
    parser.add_argument(
        "-y", "--non-interactive",
        action="store_true",
        help="Disable interactive mode (use default 'all')"
    )
    args = parser.parse_args()

    if args.list_interfaces:
        list_interfaces()
        return

    # Выбор интерфейса
    if args.interface is not None:
        interface = args.interface
        print(f"Using interface from command line: {interface}")
    elif args.non_interactive:
        interface = DEFAULT_INTERFACE
        print(f"Non-interactive mode: using '{interface}'")
    else:
        interface = interactive_interface_selection()
        if interface is None:
            print("No interface selected. Exiting.")
            return

    print(f"ZTGateway – starting on interface: {interface}, port {args.port}")

    try:
        sock = create_socket(interface, args.port, args.rcvbuf)
    except Exception as e:
        print(f"Error: {e}")
        list_interfaces()
        return

    print("Listening for DHCP requests...")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            data, client = sock.recvfrom(1024)
            mac, msg_type, hostname = parse_dhcp_packet(data)
            if mac is not None and msg_type is not None:
                print(format_packet_info(mac, msg_type, hostname, client))
            else:
                print("Received unparsable packet")
    except KeyboardInterrupt:
        print("\n\nZTGateway stopped by user")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
    finally:
        sock.close()


if __name__ == "__main__":
    main()