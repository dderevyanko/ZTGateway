
#!/usr/bin/env python3
"""
ZTGateway CLI - Zero Touch Provisioning Gateway
DHCP server for IP phones provisioning
"""

import argparse
import socket
import sys
import os
import subprocess
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


def assign_ip_permanent(interface_name: str, ip_cidr: str) -> bool:
    """
    Make IP assignment permanent by writing to /etc/network/interfaces
    Returns True if successful, False otherwise.
    """
    try:
        with open("/etc/os-release") as f:
            os_info = f.read().lower()
    except:
        os_info = ""

    # For Debian/Ubuntu with ifupdown
    if os.path.exists("/etc/network/interfaces") and ("debian" in os_info or "ubuntu" in os_info):
        backup_file = "/etc/network/interfaces.backup.ztgateway"
        try:
            subprocess.run(["sudo", "cp", "/etc/network/interfaces", backup_file], check=True)
            with open("/etc/network/interfaces", "r") as f:
                content = f.read()

            if f"auto {interface_name}" in content:
                import re
                pattern = rf"auto {interface_name}\s+iface {interface_name} inet .*?(?=\n\s*\n|\Z)"
                new_config = f"auto {interface_name}\niface {interface_name} inet static\n    address {ip_cidr}"
                new_content = re.sub(pattern, new_config, content, flags=re.DOTALL)
            else:
                new_content = content + f"\n\nauto {interface_name}\niface {interface_name} inet static\n    address {ip_cidr}\n"

            with open("/etc/network/interfaces", "w") as f:
                f.write(new_content)

            subprocess.run(["sudo", "systemctl", "restart", "networking"], check=True)
            return True
        except Exception as e:
            print(f"Failed to make IP permanent: {e}")
            return False

    # For systems with netplan (Ubuntu 18.04+)
    elif os.path.exists("/etc/netplan"):
        try:
            netplan_file = None
            for f in os.listdir("/etc/netplan"):
                if f.endswith(".yaml") or f.endswith(".yml"):
                    netplan_file = f"/etc/netplan/{f}"
                    break

            if netplan_file:
                import yaml
                netplan_config = {
                    "network": {
                        "version": 2,
                        "renderer": "networkd",
                        "ethernets": {
                            interface_name: {
                                "addresses": [ip_cidr],
                                "dhcp4": False
                            }
                        }
                    }
                }

                with open(f"/etc/netplan/99-ztgateway-{interface_name}.yaml", "w") as f:
                    yaml.dump(netplan_config, f)

                subprocess.run(["sudo", "netplan", "apply"], check=True)
                return True
        except Exception as e:
            print(f"Failed to configure netplan: {e}")
            return False

    print("Warning: Could not make IP permanent (unsupported OS). IP will be temporary.")
    return False


def interactive_interface_selection() -> Optional[Tuple[str, str]]:
    """
    Interactive selection of network interface with optional IP assignment.
    Returns (interface_name, assigned_ip) or None if cancelled.
    assigned_ip may be empty string if not applicable.
    """
    netifaces = _get_netifaces()
    if netifaces is None:
        print("netifaces not installed. Using default 'all'.")
        return (DEFAULT_INTERFACE, "")

    interfaces = []
    print("\n" + "="*60)
    print("Available Network Interfaces")
    print("="*60)

    for iface in netifaces.interfaces():
        ip = get_interface_ip(iface)
        if ip:
            print(f"  {len(interfaces)+1:2d}) {iface:20s} | Current IP: {ip:15s} | Active")
            interfaces.append({"name": iface, "ip": ip, "status": "active"})
        else:
            print(f"  {len(interfaces)+1:2d}) {iface:20s} | No IP assigned          | Inactive")
            interfaces.append({"name": iface, "ip": None, "status": "inactive"})

    print("="*60)
    print(f"  {len(interfaces)+1:2d}) all (listen on ALL interfaces)")
    print(f"  {len(interfaces)+2:2d}) Exit without starting")
    print("="*60)

    while True:
        try:
            choice = input(f"\nSelect interface (1-{len(interfaces)+2}): ").strip()

            if choice == str(len(interfaces)+2):
                return None
            if choice == str(len(interfaces)+1):
                return (DEFAULT_INTERFACE, "")

            idx = int(choice) - 1
            if 0 <= idx < len(interfaces):
                selected = interfaces[idx]
                final_ip = selected["ip"] if selected["ip"] else ""

                if selected["ip"]:
                    print(f"\nInterface '{selected['name']}' has IP: {selected['ip']}")
                    change = input("Do you want to change it? (y/N): ").strip().lower()
                    if change == 'y':
                        selected["ip"] = None
                        final_ip = ""

                if selected["ip"] is None:
                    print(f"\nConfiguring IP for '{selected['name']}'")
                    print("Example: 192.168.100.1/24")
                    ip_cidr = input("Enter IP address (CIDR format): ").strip()
                    if not ip_cidr:
                        print("No IP provided. Skipping this interface.")
                        continue

                    if ip_cidr.startswith("0.0.0.0"):
                        print("❌ Invalid IP address. 0.0.0.0 cannot be assigned to an interface.")
                        continue

                    try:
                        subprocess.run(["sudo", "ip", "addr", "flush", "dev", selected["name"]],
                                     stderr=subprocess.DEVNULL, check=False)
                        subprocess.run(["sudo", "ip", "addr", "add", ip_cidr, "dev", selected["name"]], check=True)
                        subprocess.run(["sudo", "ip", "link", "set", selected["name"], "up"], check=True)
                        print(f"✅ IP {ip_cidr} assigned temporarily to {selected['name']}")
                        final_ip = ip_cidr.split('/')[0]

                        permanent = input("Make this IP permanent? (y/N): ").strip().lower()
                        if permanent == 'y':
                            if assign_ip_permanent(selected["name"], ip_cidr):
                                print(f"✅ IP {ip_cidr} configured permanently")
                            else:
                                print("⚠️ Could not make IP permanent. It will be temporary.")
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Failed to assign IP: {e}")
                        continue

                return (selected["name"], final_ip)

            print(f"Invalid choice. Enter 1-{len(interfaces)+2}")
        except ValueError:
            print(f"Please enter a valid number (1-{len(interfaces)+2})")
        except KeyboardInterrupt:
            print("\n")
            return None


def create_socket(port: int, rcvbuf: int) -> socket.socket:
    """Create socket bound to all interfaces (0.0.0.0) for broadcast reception"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass  # not supported on macOS/Windows

    sock.bind(("", port))
    print(f"Listening on ALL interfaces, port {port}")
    return sock


def format_packet_info(
    mac: str,
    msg_type: int,
    hostname: Optional[str],
    vendor_class: Optional[str],
    client: Tuple[str, int]
) -> str:
    msg_name = DHCP_MSG_NAMES.get(msg_type, f"UNKNOWN({msg_type})")
    
    parts = [f"{msg_name} from {mac}"]
    if hostname:
        parts.append(f"hostname={hostname}")
    if vendor_class:
        parts.append(f"vendor={vendor_class}")
    parts.append(f"src={client[0]}:{client[1]}")
    
    return ", ".join(parts)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ZTGateway – Zero Touch Provisioning Gateway"
    )
    parser.add_argument(
        "-i", "--interface",
        default=None,
        help="Network interface to use for responses (e.g., eth0, enx00e04c150bdf)"
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

    # Выбор интерфейса для ответов
    if args.interface is not None:
        interface = args.interface
        server_ip = get_interface_ip(interface)
        if not server_ip and interface != "all":
            print(f"Warning: Interface {interface} has no IP address.")
        print(f"Using interface from command line: {interface}")
    elif args.non_interactive:
        interface = DEFAULT_INTERFACE
        server_ip = None
        print(f"Non-interactive mode: using '{interface}'")
    else:
        result = interactive_interface_selection()
        if result is None:
            print("No interface selected. Exiting.")
            return
        interface, server_ip = result
        print(f"Selected interface: {interface}")
        if server_ip:
            print(f"Using IP for responses: {server_ip}")

    # Сокет всегда слушает все интерфейсы (для приема broadcast)
    sock = create_socket(args.port, args.rcvbuf)

    print("Listening for DHCP requests...")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            data, client = sock.recvfrom(1024)
            mac, msg_type, hostname, vendor_class = parse_dhcp_packet(data)
            if mac is not None and msg_type is not None:
                print(format_packet_info(mac, msg_type, hostname, vendor_class, client))
                # TODO: Implement DHCPOFFER response here
                # Use server_ip for siaddr, option 54, option 66
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
