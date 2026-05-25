import socket
import struct
import time
import threading
import json
import os
import gi

# Request both GTK 4 and Libadwaita 1
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk

# ==============================================================================
# CONFIGURATION DEFAULTS & PERSISTENCE
# ==============================================================================

# Shift light visual feedback colors (RGBA)
SHIFT_ACTIVE_COLOR = "rgba(255, 40, 0, 0.4)"  # Dark orange
SHIFT_IDLE_COLOR = "rgba(0, 0, 0, 0)"  # Transparent

CONFIG_FILE = os.path.join(os.getcwd(), "config.json")

DEFAULT_CONFIG = {
    "shift_threshold": 0.85,
    "forza_port": 8000,
    "keepalive_interval": 0.5,
    "devices": [
        {
            "name": "Desk",
            "ip": "192.168.0.121",
            "port": 21324,
            "total_leds": 47,
            "ranges": [[[18, 30], [255, 20, 0]]]
        },
        {
            "name": "Monitor",
            "ip": "192.168.0.122",
            "port": 21324,
            "total_leds": 130,
            "ranges": [[[66, 125], [255, 20, 0]]]
        }
    ]
}

def load_system_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
    except Exception as e:
        print(f"Error creating default config: {e}")
    return DEFAULT_CONFIG

def save_full_config():
    try:
        current_config["shift_threshold"] = SHIFT_THRESHOLD
        current_config["forza_port"] = FORZA_PORT
        current_config["keepalive_interval"] = KEEPALIVE_INTERVAL
        current_config["devices"] = DEVICES
        with open(CONFIG_FILE, "w") as f:
            json.dump(current_config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

current_config = load_system_config()
SHIFT_THRESHOLD = current_config.get("shift_threshold", 0.85)
FORZA_PORT = current_config.get("forza_port", 8000)
KEEPALIVE_INTERVAL = current_config.get("keepalive_interval", 0.5)
DEVICES = current_config.get("devices", [])

# ==============================================================================
# UDP COMMUNICATION & TELEMETRY
# ==============================================================================

wled_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
forza_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    forza_sock.bind(("0.0.0.0", FORZA_PORT))
except Exception as e:
    print(f"Warning: Could not bind telemetry port {FORZA_PORT}: {e}")

def build_wled_packet(total_leds, ranges, on):
    packet = bytearray([1, 2])
    for i in range(total_leds):
        packet.append(i)
        color = [0, 0, 0]
        if on:
            for bounds, r_color in ranges:
                if bounds[0] <= i <= bounds[1]:
                    color = r_color
                    break
        packet.extend(color)
    return packet

def send_all_devices(on):
    for device in DEVICES:
        packet = build_wled_packet(device["total_leds"], device["ranges"], on)
        try:
            wled_sock.sendto(packet, (device["ip"], device["port"]))
        except Exception:
            pass

shift_on = False
last_send = 0
current_ratio = 0.0

def telemetry_loop():
    global shift_on, last_send, current_ratio
    while True:
        try:
            data, _ = forza_sock.recvfrom(1024)
            max_rpm = struct.unpack_from("<f", data, 8)[0]
            current_rpm = struct.unpack_from("<f", data, 16)[0]

            if max_rpm <= 0:
                if shift_on:
                    shift_on = False
                    send_all_devices(False)
                    last_send = time.time()
                continue

            current_ratio = current_rpm / max_rpm
            now = time.time()

            if not shift_on and current_ratio >= SHIFT_THRESHOLD:
                shift_on, last_send = True, now
                send_all_devices(True)
            elif shift_on and current_ratio < SHIFT_THRESHOLD:
                shift_on, last_send = False, now
                send_all_devices(False)
            elif now - last_send > KEEPALIVE_INTERVAL:
                send_all_devices(shift_on)
                last_send = now
        except Exception:
            pass

# ==============================================================================
# LIBADWAITA PREFERENCES MANAGEMENT PANELS
# ==============================================================================

class DeviceFormWindow(Adw.PreferencesWindow):
    """
    Edit or create a single WLED device.

    Every widget is wired to write through to self.device_data immediately and
    call save_full_config() so the JSON is always up-to-date, regardless of
    whether the user clicks "Save" or just closes the window.
    """

    def __init__(self, parent, device_index, on_close_callback=None):
        """
        Parameters
        ----------
        parent            : transient parent window
        device_index      : int index into DEVICES list, or -1 for a new device
        on_close_callback : called with no arguments after the window closes so
                            the caller can refresh its list
        """
        super().__init__(transient_for=parent, modal=True,
                         default_width=680, default_height=560)
        self.on_close_callback = on_close_callback
        self.device_index = device_index

        # If editing an existing device, work on the live DEVICES entry directly.
        # If adding a new one, append a blank template first so every change
        # immediately lands in DEVICES and gets persisted.
        if device_index == -1:
            new_device = {
                "name": "",
                "ip": "192.168.0.100",
                "port": 21324,
                "total_leds": 60,
                "ranges": [[[0, 10], [255, 20, 0]]]
            }
            DEVICES.append(new_device)
            self.device_index = len(DEVICES) - 1
            save_full_config()

        # Always reference the live dict so mutations are visible everywhere.
        self.device_data = DEVICES[self.device_index]

        self.connect("close-request", self._on_close_request)

        self.pref_page = Adw.PreferencesPage()
        self.add(self.pref_page)

        # ------------------------------------------------------------------
        # Device parameters group
        # ------------------------------------------------------------------
        net_group = Adw.PreferencesGroup(title="Device Parameters")
        self.pref_page.add(net_group)

        name_row = Adw.ActionRow(title="Device Name")
        self.name_entry = Gtk.Entry(
            text=self.device_data.get("name", ""),
            valign=Gtk.Align.CENTER,
            placeholder_text="e.g. Desk Light"
        )
        self.name_entry.connect("changed", self._on_name_changed)
        name_row.add_suffix(self.name_entry)
        net_group.add(name_row)

        ip_row = Adw.ActionRow(title="IP Address")
        self.ip_entry = Gtk.Entry(
            text=self.device_data.get("ip", "192.168.0.100"),
            valign=Gtk.Align.CENTER
        )
        self.ip_entry.connect("changed", self._on_ip_changed)
        ip_row.add_suffix(self.ip_entry)
        net_group.add(ip_row)

        led_row = Adw.ActionRow(title="Total LED Count")
        self.leds_spin = Gtk.SpinButton.new_with_range(1, 2048, 1)
        self.leds_spin.set_value(self.device_data.get("total_leds", 60))
        self.leds_spin.set_valign(Gtk.Align.CENTER)
        self.leds_spin.connect("value-changed", self._on_leds_changed)
        led_row.add_suffix(self.leds_spin)
        net_group.add(led_row)

        # ------------------------------------------------------------------
        # Zones group (rebuilt on every add/remove)
        # ------------------------------------------------------------------
        self.zones_group = None
        self._render_zones()

    # ------------------------------------------------------------------
    # Immediate-save callbacks for top-level device fields
    # ------------------------------------------------------------------

    def _on_name_changed(self, entry):
        self.device_data["name"] = entry.get_text()
        save_full_config()

    def _on_ip_changed(self, entry):
        self.device_data["ip"] = entry.get_text()
        save_full_config()

    def _on_leds_changed(self, spin):
        self.device_data["total_leds"] = int(spin.get_value())
        save_full_config()

    # ------------------------------------------------------------------
    # Zone rendering
    # ------------------------------------------------------------------

    def _render_zones(self):
        if self.zones_group:
            self.pref_page.remove(self.zones_group)

        self.zones_group = Adw.PreferencesGroup(title="Active LED Zones")
        add_zone_btn = Gtk.Button(icon_name="list-add-symbolic",
                                  valign=Gtk.Align.CENTER)
        add_zone_btn.add_css_class("flat")
        add_zone_btn.connect("clicked", self._on_add_zone)
        self.zones_group.set_header_suffix(add_zone_btn)
        self.pref_page.add(self.zones_group)

        for idx, zone in enumerate(self.device_data["ranges"]):
            zone_row = Adw.ActionRow(title=f"Zone Profile #{idx + 1}")
            controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=8, valign=Gtk.Align.CENTER)

            # From spinner
            start_spin = Gtk.SpinButton.new_with_range(0, 4096, 1)
            start_spin.set_value(zone[0][0])
            start_spin.set_size_request(80, -1)
            start_spin.connect("value-changed",
                               self._on_zone_bound_changed, idx, 0)
            controls.append(Gtk.Label(label="From:"))
            controls.append(start_spin)

            # To spinner
            end_spin = Gtk.SpinButton.new_with_range(0, 4096, 1)
            end_spin.set_value(zone[0][1])
            end_spin.set_size_request(80, -1)
            end_spin.connect("value-changed",
                             self._on_zone_bound_changed, idx, 1)
            controls.append(Gtk.Label(label="To:"))
            controls.append(end_spin)

            # Color button
            color_btn = Gtk.ColorDialogButton()
            color_btn.set_dialog(Gtk.ColorDialog())
            rgba = Gdk.RGBA()
            r, g, b = zone[1][0], zone[1][1], zone[1][2]
            rgba.parse(f"rgb({r},{g},{b})")
            color_btn.set_rgba(rgba)
            # Use a closure to capture idx at definition time
            color_btn.connect("notify::rgba",
                              self._make_color_handler(idx))
            controls.append(color_btn)

            # Delete button
            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.add_css_class("destructive-action")
            del_btn.connect("clicked", self._on_remove_zone, idx)
            controls.append(del_btn)

            zone_row.add_suffix(controls)
            self.zones_group.add(zone_row)

    # ------------------------------------------------------------------
    # Immediate-save callbacks for zone fields
    # ------------------------------------------------------------------

    def _on_zone_bound_changed(self, spin, idx, pos):
        """pos=0 → start bound, pos=1 → end bound."""
        self.device_data["ranges"][idx][0][pos] = int(spin.get_value())
        save_full_config()

    def _make_color_handler(self, idx):
        """Return a unique closure so idx is captured correctly per zone."""
        def handler(btn, _param):
            rgba = btn.get_rgba()
            self.device_data["ranges"][idx][1] = [
                int(rgba.red * 255),
                int(rgba.green * 255),
                int(rgba.blue * 255),
            ]
            save_full_config()
        return handler

    def _on_add_zone(self, _button):
        self.device_data["ranges"].append([[0, 10], [255, 20, 0]])
        save_full_config()
        self._render_zones()

    def _on_remove_zone(self, _button, idx):
        if len(self.device_data["ranges"]) > 1:
            self.device_data["ranges"].pop(idx)
            save_full_config()
            self._render_zones()

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------

    def _on_close_request(self, _window):
        if self.on_close_callback:
            self.on_close_callback()
        return False  # allow close to proceed


class ConfigWindow(Adw.PreferencesWindow):
    def __init__(self, parent, on_save_notify):
        super().__init__(transient_for=parent, modal=True,
                         default_width=520, default_height=500)
        self.on_save_notify = on_save_notify

        self.pref_page = Adw.PreferencesPage()
        self.add(self.pref_page)

        global_group = Adw.PreferencesGroup(title="Telemetry Configuration")
        self.pref_page.add(global_group)

        gr1 = Adw.ActionRow(title="Incoming Telemetry Port")
        self.port_spin = Gtk.SpinButton.new_with_range(1024, 65535, 1)
        self.port_spin.set_value(FORZA_PORT)
        self.port_spin.set_valign(Gtk.Align.CENTER)
        self.port_spin.connect("value-changed", self._on_port_changed)
        gr1.add_suffix(self.port_spin)
        global_group.add(gr1)

        gr2 = Adw.ActionRow(title="Network Keepalive Fallback")
        self.keepalive_spin = Gtk.SpinButton.new_with_range(0.1, 5.0, 0.1)
        self.keepalive_spin.set_value(KEEPALIVE_INTERVAL)
        self.keepalive_spin.set_valign(Gtk.Align.CENTER)
        self.keepalive_spin.connect("value-changed", self._on_keepalive_changed)
        gr2.add_suffix(self.keepalive_spin)
        global_group.add(gr2)

        self.devices_group = None
        self.populate_devices()

    # ------------------------------------------------------------------
    # Immediate-save for global settings
    # ------------------------------------------------------------------

    def _on_port_changed(self, spin):
        global FORZA_PORT
        FORZA_PORT = int(spin.get_value())
        save_full_config()
        self.on_save_notify()

    def _on_keepalive_changed(self, spin):
        global KEEPALIVE_INTERVAL
        KEEPALIVE_INTERVAL = spin.get_value()
        save_full_config()
        self.on_save_notify()

    # ------------------------------------------------------------------
    # Device list
    # ------------------------------------------------------------------

    def populate_devices(self):
        if self.devices_group:
            self.pref_page.remove(self.devices_group)

        self.devices_group = Adw.PreferencesGroup(title="WLED Network Controllers")
        add_dev_btn = Gtk.Button(icon_name="list-add-symbolic",
                                 valign=Gtk.Align.CENTER)
        add_dev_btn.add_css_class("flat")
        add_dev_btn.connect("clicked", self.on_add_device_clicked)
        self.devices_group.set_header_suffix(add_dev_btn)
        self.pref_page.add(self.devices_group)

        for index, device in enumerate(DEVICES):
            action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                 spacing=4, valign=Gtk.Align.CENTER)

            edit_btn = Gtk.Button(icon_name="document-edit-symbolic")
            edit_btn.add_css_class("flat")
            edit_btn.connect("clicked", self.on_edit_device_clicked, index)
            action_box.append(edit_btn)

            del_btn = Gtk.Button(icon_name="user-trash-symbolic")
            del_btn.add_css_class("flat")
            del_btn.add_css_class("destructive-action")
            del_btn.connect("clicked", self.on_delete_device_clicked, index)
            action_box.append(del_btn)

            dev_row = Adw.ActionRow(
                title=device["name"],
                subtitle=f"{device['ip']} • {len(device['ranges'])} zones"
            )
            dev_row.add_suffix(action_box)
            self.devices_group.add(dev_row)

    def on_add_device_clicked(self, _button):
        form = DeviceFormWindow(self, device_index=-1,
                                on_close_callback=self.populate_devices)
        form.present()

    def on_edit_device_clicked(self, _button, idx):
        form = DeviceFormWindow(self, device_index=idx,
                                on_close_callback=self.populate_devices)
        form.present()

    def on_delete_device_clicked(self, _button, idx):
        DEVICES.pop(idx)
        save_full_config()
        self.populate_devices()


# ==============================================================================
# MAIN APPLICATION INTERFACE
# ==============================================================================

class ShiftLightWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Forza Shift Light")
        self.set_default_size(440, -1)

        self.setup_custom_css()

        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        self.header_bar = Adw.HeaderBar()
        self.header_bar.add_css_class("shift-header-idle")
        toolbar_view.add_top_bar(self.header_bar)

        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.connect("clicked", self.on_settings_clicked)
        self.header_bar.pack_end(settings_btn)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.set_vexpand(True)
        self.main_box.add_css_class("shift-window-idle")
        toolbar_view.set_content(self.main_box)

        pref_page = Adw.PreferencesPage()
        self.main_box.append(pref_page)

        config_group = Adw.PreferencesGroup()
        pref_page.add(config_group)

        self.threshold_spin = Adw.SpinRow.new_with_range(0, 100, 5)
        self.threshold_spin.set_title("Shift Threshold")
        self.threshold_spin.set_subtitle(
            "Activate shift light at this percentage of max RPM")
        self.threshold_spin.set_value(int(SHIFT_THRESHOLD * 100))
        self.threshold_spin.connect("notify::value", self.on_spin_value_changed)
        config_group.add(self.threshold_spin)

        GLib.timeout_add(50, self.update_ui)

    def setup_custom_css(self):
        css_data = f"""
        .shift-window-idle {{
            background-color: {SHIFT_IDLE_COLOR};
            transition: all 100ms ease-in-out;
        }}
        .shift-window-active {{
            background-color: {SHIFT_ACTIVE_COLOR};
            transition: all 50ms ease-in-out;
        }}
        .shift-header-idle {{
            background-color: {SHIFT_IDLE_COLOR};
            transition: all 100ms ease-in-out;
        }}
        .shift-header-active {{
            background-color: {SHIFT_ACTIVE_COLOR};
            transition: all 50ms ease-in-out;
        }}
        """.encode()
        provider = Gtk.CssProvider()
        provider.load_from_data(css_data)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def on_settings_clicked(self, _button):
        config_win = ConfigWindow(self, self.on_config_saved_refresh)
        config_win.present()

    def on_config_saved_refresh(self):
        self.threshold_spin.set_value(int(SHIFT_THRESHOLD * 100))

    def on_spin_value_changed(self, spin, _param):
        global SHIFT_THRESHOLD
        SHIFT_THRESHOLD = int(spin.get_value()) / 100.0
        save_full_config()

    def update_ui(self):
        if shift_on:
            if "shift-window-idle" in self.main_box.get_css_classes():
                self.main_box.remove_css_class("shift-window-idle")
                self.main_box.add_css_class("shift-window-active")
            if "shift-header-idle" in self.header_bar.get_css_classes():
                self.header_bar.remove_css_class("shift-header-idle")
                self.header_bar.add_css_class("shift-header-active")
        else:
            if "shift-window-active" in self.main_box.get_css_classes():
                self.main_box.remove_css_class("shift-window-active")
                self.main_box.add_css_class("shift-window-idle")
            if "shift-header-active" in self.header_bar.get_css_classes():
                self.header_bar.remove_css_class("shift-header-active")
                self.header_bar.add_css_class("shift-header-idle")
        return True


# ==============================================================================
# APPLICATION INITIALIZATION
# ==============================================================================

def on_app_activate(application):
    application.get_style_manager().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
    window = ShiftLightWindow(application)
    window.present()

threading.Thread(target=telemetry_loop, daemon=True).start()

app = Adw.Application(application_id="com.forza.shiftlight")
app.connect("activate", on_app_activate)
app.run()