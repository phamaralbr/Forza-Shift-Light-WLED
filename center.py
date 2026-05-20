import socket
import struct
import time

# =========================
# CONFIG
# =========================

WLED_IP = "192.168.0.121"
WLED_PORT = 21324
NUM_LEDS = 47

FORZA_PORT = 8000

SHIFT_THRESHOLD = 0.80
HYSTERESIS = 0

CENTER_LED = 24
ACTIVE_LEDS = 7  # total lit LEDs when shift is ON

# =========================
# SOCKETS
# =========================

wled_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

forza_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
forza_sock.bind(("0.0.0.0", FORZA_PORT))

# =========================
# STATE
# =========================

shift_on = False
last_send = 0
KEEPALIVE_INTERVAL = 0.5

# =========================
# WLED REALTIME
# =========================

def send_shift_light(on):
    packet = bytearray()

    packet.append(1)  # WARLS
    packet.append(2)  # timeout

    if on:
        color = (255, 80, 0)

        half = ACTIVE_LEDS // 2
        start = CENTER_LED - half
        end = CENTER_LED + half

        for i in range(NUM_LEDS):
            if start <= i <= end:
                c = color
            else:
                c = (0, 0, 0)

            packet.append(i)
            packet.append(c[0])
            packet.append(c[1])
            packet.append(c[2])
    else:
        # all off
        for i in range(NUM_LEDS):
            packet.append(i)
            packet.append(0)
            packet.append(0)
            packet.append(0)

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

        # ON
        if not shift_on and ratio >= SHIFT_THRESHOLD:
            shift_on = True
            print(f"SHIFT! {ratio:.2f}")
            send_shift_light(True)
            last_send = time.time()

        # OFF
        elif shift_on and ratio <= (SHIFT_THRESHOLD - HYSTERESIS):
            shift_on = False
            print(f"off {ratio:.2f}")
            send_shift_light(False)
            last_send = time.time()

        # keepalive
        elif time.time() - last_send > KEEPALIVE_INTERVAL:
            send_shift_light(shift_on)
            last_send = time.time()

    except Exception as e:
        print("Telemetry parse error:", e)