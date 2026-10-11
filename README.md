# yeelight-onboard

Put a Yeelight lamp on your WiFi **without the Yeelight or Mi Home app**, switch
on LAN Control, and keep the lamp's token for Home Assistant and other local tools.

## Usage

1. Reset the lamp so it is in setup mode and broadcasts its own WiFi network
   (for example `yeelink-light-ceiling3_...`). For many ceiling lights: switch
   the wall switch off and on 5 times, about 2 seconds each.
2. Connect your computer to the lamp's network.
3. Run:

   ```
   pip install python-miio==0.5.12
   ./yeelight_onboard.py "Your WiFi name"
   ```

   You are asked for the WiFi password without echo (piping it in also works).
   The script finds the lamp at `<your subnet>.1`; use `--ip` if that guess is
   wrong.
4. Reconnect your computer to your own WiFi. Look up the lamp's address in your
   router.

What the script does:

- reads the lamp's token through the miIO handshake (a lamp in setup mode
  reveals it) and saves it in `~/yeelight-<device id>.json`, readable only by
  you. The token is never printed;
- switches on **LAN Control** (developer mode, TCP port 55443), which Home
  Assistant's Yeelight integration needs and which normally requires the app
  (use `--no-lan-control` to skip);
- sends your WiFi name and password (`miIO.config_router`).

To switch LAN Control on (or off) later, run this from a computer on the same
subnet as the lamp. The script then checks whether TCP port 55443 opened or closed.
This needs the lamp to answer miIO commands after setup, which not all firmware
does (see Status):

```
./yeelight_onboard.py --lan-control on --ip <lamp ip> --token-file ~/yeelight-<device id>.json
```

## Home Assistant

Add the **Yeelight** integration with the lamp's address. If the lamp is on
another subnet or VLAN than Home Assistant, discovery doesn't work, the model
shows as "Unknown" and features such as the ceiling light's moonlight mode are
missing: set the model in the integration's options (e.g. `ceiling3`) and
enable "nightlight switch".

Seen on the tested lamp: from another subnet it answered LAN Control (TCP 55443)
but not discovery (UDP 1982) or miIO (UDP 54321).

## Status

Tested on a Yeelight ceiling3 with firmware 2.0.2: setup works and LAN Control is
on afterwards (TCP 55443 open, Home Assistant connects). After setup this lamp no
longer answered miIO commands, not even from the same subnet, so `--lan-control`
did not work on it; switching LAN Control during setup is the reliable way.
Firmware updates still need the app.

The tests in `tests/` use a fake python-miio and need no lamp:
`python3 tests/test_yeelight_onboard.py`.

## License

GPL-3.0 (python-miio, which this script uses, is GPL-3.0). LIFX bulbs: see
[tserong/lifx-hacks](https://github.com/tserong/lifx-hacks).
