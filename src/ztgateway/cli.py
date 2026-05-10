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
    # Detect OS (Debian/Ubuntu vs others)
    try:
        with open("/etc/os-release") as f:
            os_info = f.read().lower()
    except:
        os_info = ""
    
    # For Debian/Ubuntu with ifupdown
    if os.path.exists("/etc/network/interfaces") and ("debian" in os_info or "ubuntu" in os_info):
        backup_file = "/etc/network/interfaces.backup.ztgateway"
        try:
            # Create backup
            subprocess.run(["sudo", "cp", "/etc/network/interfaces", backup_file], check=True)
            
            # Check if interface already configured
            with open("/etc/network/interfaces", "r") as f:
                content = f.read()
            
            if f"auto {interface_name}" in content:
                # Replace existing configuration
                import re
                pattern = rf"auto {interface_name}\s+iface {interface_name} inet .*?(?=\n\s*\n|\Z)"
                new_config = f"auto {interface_name}\niface {interface_name} inet static\n    address {ip_cidr}"
                new_content = re.sub(pattern, new_config, content, flags=re.DOTALL)
            else:
                # Add new configuration
                new_content = content + f"\n\nauto {interface_name}\niface {interface_name} inet static\n    address {ip_cidr}\n"
            
            with open("/etc/network/interfaces", "w") as f:
                f.write(new_content)
            
            # Apply changes
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
                with open(netplan_file, "r") as f:
                    config = yaml.safe_load(f)
                
                # Simplified: just create a new netplan config for the interface
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
                
                # Ask if user wants to change/assign IP
                if selected["ip"]:
                    print(f"\nInterface '{selected['name']}' has IP: {selected['ip']}")
                    change = input("Do you want to change it? (y/N): ").strip().lower()
                    if change == 'y':
                        selected["ip"] = None  # Force manual assignment
                        final_ip = ""
                
                if selected["ip"] is None:
                    print(f"\nConfiguring IP for '{selected['name']}'")
                    print("Example: 192.168.100.1/24")
                    ip_cidr = input("Enter IP address (CIDR format): ").strip()
                    if not ip_cidr:
                        print("No IP provided. Skipping this interface.")
                        continue
                    
                    # Assign IP temporarily
                    try:
                        # Flush existing IP if any
                        subprocess.run(["sudo", "ip", "addr", "flush", "dev", selected["name"]], 
                                     stderr=subprocess.DEVNULL, check=False)
                        # Add new IP
                        subprocess.run(["sudo", "ip", "addr", "add", ip_cidr, "dev", selected["name"]], check=True)
                        subprocess.run(["sudo", "ip", "link", "set", selected["name"], "up"], check=True)
                        print(f"✅ IP {ip_cidr} assigned temporarily to {selected['name']}")
                        final_ip = ip_cidr.split('/')[0]
                        
                        # Ask to make permanent
                        permanent = input("Make this IP permanent? (y/N): ").strip().lower()
                        if permanent == 'y':
                            if assign_ip_permanent(selected["name"], ip_cidr):
                                print(f"✅ IP {ip_cidr} configured permanently")
                            else:
                                print("⚠️  Could not make IP permanent. It will be temporary.")
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

    # Выбор интерфейса (интерактивный или через аргументы)
    if args.interface is not None:
        interface = args.interface
        print(f"Using interface from command line: {interface}")
    elif args.non_interactive:
        interface = DEFAULT_INTERFACE
        print(f"Non-interactive mode: using '{interface}'")
    else:
        result = interactive_interface_selection()
        if result is None:
            print("No interface selected. Exiting.")
            return
        interface, assigned_ip = result
        print(f"Selected interface: {interface}")
        if assigned_ip:
            print(f"Using IP: {assigned_ip}")

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