import struct

# DHCP message types (RFC 2132)
DHCPDISCOVER = 1
DHCPOFFER = 2
DHCPREQUEST = 3
DHCPACK = 5

def parse_dhcp_packet(data: bytes):
    """
    Extracts MAC address, DHCP message type, and hostname (option 12).
    Returns (mac, msg_type, hostname) or (None, None, None) on error.
    """
    # Minimum DHCP packet length is 240 bytes
    if len(data) < 240:
        return None, None, None

    # Extract MAC address (bytes 28-33)
    mac_bytes = data[28:34]
    mac = ":".join(f"{b:02x}" for b in mac_bytes)

    # Verify Magic Cookie (bytes 236-239 must be 0x63825363)
    cookie = struct.unpack("!I", data[236:240])[0]
    if cookie != 0x63825363:
        return None, None, None

    # Parse DHCP options
    idx = 240
    msg_type = None
    hostname = None

    while idx < len(data):
        option_code = data[idx]

        # Pad option (skip single byte)
        if option_code == 0:
            idx += 1
            continue

        # End of options
        if option_code == 255:
            break

        # Ensure we have enough bytes for length
        if idx + 1 >= len(data):
            break

        option_len = data[idx + 1]

        # Validate option boundaries
        if idx + 2 + option_len > len(data):
            break

        # Option 53: DHCP Message Type
        if option_code == 53 and option_len >= 1:
            msg_type = data[idx + 2]

        # Option 12: Hostname
        elif option_code == 12 and option_len > 0:
            try:
                hostname = data[idx + 2:idx + 2 + option_len].decode('utf-8', errors='ignore')
            except:
                hostname = None

        # Move to next option
        idx += 2 + option_len

    return mac, msg_type, hostname