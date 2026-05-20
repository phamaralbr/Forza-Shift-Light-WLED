import socket
import struct

# =========================
# CONFIG
# =========================

WLED_IP = "192.168.0.121"
WLED_PORT = 21324
NUM_LEDS = 47

FORZA_PORT = 8000

CENTER_LED = 26
REDLINE = 0.80

# =========================
# SOCKETS
# =========================

wled_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

forza_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
forza_sock.bind(("0.0.0.0", FORZA_PORT))

# =========================
# COLOR MAP (green → yellow → red)
# =========================

def rpm_color(r):
    r = max(0.0, min(1.0, r))

    if r < 0.5:
        # green → yellow
        t = r / 0.5
        return (int(255 * t), 255, 0)
    else:
        # yellow → red
        t = (r - 0.5) / 0.5
        return (255, int(255 * (1 - t)), 0)

# =========================
# WLED REALTIME
# =========================

def send_shift_bar(ratio):
    packet = bytearray()

    packet.append(1)  # WARLS
    packet.append(2)  # timeout

    ratio = max(0.0, min(1.0, ratio))

    # full red at redline
    if ratio >= REDLINE:
        color = (255, 0, 0)
        for i in range(NUM_LEDS):
            packet.append(i)
            packet.append(color[0])
            packet.append(color[1])
            packet.append(color[2])

        wled_sock.sendto(packet, (WLED_IP, WLED_PORT))
        return

    # how far from edges inward
    max_side = min(CENTER_LED, NUM_LEDS - CENTER_LED - 1)
    active = int(ratio / REDLINE * max_side)

    for i in range(NUM_LEDS):
        dist_left = i
        dist_right = NUM_LEDS - 1 - i
        dist_edge = min(dist_left, dist_right)

        if dist_edge <= active:
            color = rpm_color(ratio)
        else:
            color = (0, 0, 0)

        packet.append(i)
        packet.append(color[0])
        packet.append(color[1])
        packet.append(color[2])

    wled_sock.sendto(packet, (WLED_IP, WLED_PORT))

# =========================
# MAIN LOOP
# =========================

print("Waiting for Forza telemetry...")

while True:
    data, addr = forza_sock.recvfrom(1024)

    try:
        max_rpm = struct.unpack_from("<f", data, 8)[0]
        current_rpm = struct.unpack_from("<f", data, 16)[0]

        if max_rpm <= 0:
            continue

        ratio = current_rpm / max_rpm
        ratio = max(0.0, min(1.0, ratio))

        print(f"RPM: {ratio:.2f}")

        send_shift_bar(ratio)

    except Exception as e:
        print("Telemetry parse error:", e)