#!/usr/bin/env python3
"""Put a Yeelight lamp in setup mode on your WiFi, without the Yeelight or Mi Home app.

Setup (lamp broadcasts its own network, e.g. "yeelink-light-ceiling3_..."):
    1. Connect this computer to the lamp's network.
    2. ./yeelight_onboard.py "Your WiFi name"        (asks the password without echo)
    3. Reconnect this computer to your own WiFi.

The lamp's token (needed by Home Assistant and other tools) is saved in
~/yeelight-<device id>.json (readable only by you) and never printed.
LAN Control ("developer mode", TCP port 55443) is switched on before the lamp
leaves setup mode, so Home Assistant's Yeelight integration works without the app.

Switch LAN Control on or off later (from a computer on the same subnet as the lamp):
    ./yeelight_onboard.py --lan-control on --ip <lamp ip> --token-file ~/yeelight-<id>.json

Uses python-miio (pip install python-miio==0.5.12).
"""
import argparse
import getpass
import json
import os
import pathlib
import socket
import sys
import time

from miio import Device
from miio.miioprotocol import MiIOProtocol

LAN_PORT = 55443


def lan_control_command(on):
    # same as python-miio Yeelight.set_developer_mode(on)
    return "set_ps", ["cfg_lan_ctrl", "1" if on else "0"]


def port_open(ip, port=LAN_PORT, timeout=3):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def guess_lamp_ip():
    """In setup mode the lamp is the router of its own network, usually <subnet>.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the route
        local = s.getsockname()[0]
    return local.rsplit(".", 1)[0] + ".1"


def save_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)  # also when the file already existed


def read_password(interactive):
    if interactive:
        return getpass.getpass("WiFi password (not shown): ")
    return sys.stdin.readline().rstrip("\n")


def set_lan_control(dev, on):
    try:
        print(f"LAN Control {'on' if on else 'off'}:", dev.send(*lan_control_command(on)))
        return True
    except Exception as e:  # informative only; can be done later with --lan-control
        print(f"LAN Control could not be switched {'on' if on else 'off'}: {type(e).__name__}: {e}")
        return False


def onboard(args):
    ip = args.ip or guess_lamp_ip()
    print(f"Lamp address: {ip}{'' if args.ip else ' (guessed, use --ip to override)'}")

    hello = MiIOProtocol(ip, timeout=5).send_handshake()
    token = hello.checksum
    if token in (b"\x00" * 16, b"\xff" * 16):
        sys.exit("The lamp does not reveal its token: it is already set up or its firmware "
                 "hides it. Reset the lamp and try again.")
    device_id = hello.header.value.device_id.hex()
    record = {"device_id": device_id, "token": token.hex(), "setup_ip": ip}
    path = pathlib.Path(args.out).expanduser() / f"yeelight-{device_id}.json"
    save_private(path, record)
    print(f"Handshake ok (device id {device_id}); token saved in {path}")

    dev = Device(ip, token.hex())
    try:
        info = dev.info()  # never print info itself: its repr contains the token
        record.update(model=info.model, firmware=info.firmware_version, mac=info.mac_address)
        save_private(path, record)
        print(f"Lamp: {info.model}, firmware {info.firmware_version}, MAC {info.mac_address}")
    except Exception as e:
        print(f"Could not read device info: {type(e).__name__}: {e}")

    if not args.no_lan_control:
        set_lan_control(dev, True)

    try:
        print("WiFi settings sent, lamp answered:", dev.configure_wifi(args.ssid, args.password or ""))
    except Exception as e:
        # the lamp may switch networks right away and not answer anymore
        print(f"WiFi settings sent, no answer from the lamp ({type(e).__name__}); "
              "that is normal if its own network disappears now.")

    print("Next: reconnect to your own WiFi and look up the lamp's address in your router.\n"
          "Home Assistant: add the Yeelight integration with that address. If the model shows as\n"
          "'Unknown', set it in the integration's options.")


def lan_control_only(args, wait=10):
    if not (args.ip and args.token_file):
        sys.exit("--lan-control needs --ip and --token-file")
    on = args.lan_control == "on"
    record = json.loads(pathlib.Path(args.token_file).expanduser().read_text())
    if not set_lan_control(Device(args.ip, record["token"]), on):
        sys.exit("The lamp did not answer. It must be on the same subnet as this computer, and some\n"
                 "firmware (seen on a ceiling3 with 2.0.2) stops answering these commands after\n"
                 "setup. In that case LAN Control can only be set during setup (the default) or in the app.")
    for attempt in range(wait):  # the lamp opens or closes the port within a few seconds
        if port_open(args.ip, timeout=1) == on:
            print(f"Checked: TCP port {LAN_PORT} is {'open' if on else 'closed'}.")
            return
        if attempt < wait - 1:
            time.sleep(1)
    sys.exit(f"The lamp accepted the command, but TCP port {LAN_PORT} is still "
             f"{'closed' if on else 'open'}.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Onboard a Yeelight lamp onto your WiFi without the app.")
    parser.add_argument("ssid", nargs="?", help="name of the WiFi network the lamp should join")
    parser.add_argument("password", nargs="?", help="WiFi password (omit it to be asked without echo)")
    parser.add_argument("--ip", help="lamp address (default: guessed from this computer's network)")
    parser.add_argument("--out", default="~", help="folder for the token file (default: your home folder)")
    parser.add_argument("--no-lan-control", action="store_true", help="don't switch on LAN Control during setup")
    parser.add_argument("--lan-control", choices=("on", "off"),
                        help="only switch LAN Control on or off on an already set-up lamp (needs --ip and --token-file)")
    parser.add_argument("--token-file", help="token file written during setup")
    args = parser.parse_args(argv)

    if args.lan_control:
        return lan_control_only(args)
    if not args.ssid:
        parser.error("the WiFi name (ssid) is required")
    if args.password is None:
        args.password = read_password(sys.stdin.isatty())
    if not 0 < len(args.ssid.encode("utf-8")) <= 32 or len(args.password.encode("utf-8")) > 64:
        sys.exit("The WiFi name must be 1-32 bytes and the password at most 64 bytes.")
    onboard(args)


if __name__ == "__main__":
    main()
