# Stage firmware (Arduino Nano · 28BYJ-48 · ULN2003)

`cnc/cnc.ino` speaks protocol v2 with the station (`backend/app/core/motion_protocol.py`).

Idle coils switch off 3 s after each command (`IDLE_RELEASE_MS`) so the motors stay cool;
position and HOME are kept (the 1:64 gearbox holds the axis). `RELEASE` switches them off
at once; `OFF` also clears HOME.

## Flash from the Jetson (the Nano is on its USB)

```bash
./aoi-stop                                    # free /dev/ttyUSB0
arduino-cli compile -b arduino:avr:nano:cpu=atmega328old firmware/cnc
arduino-cli upload  -b arduino:avr:nano:cpu=atmega328old -p /dev/ttyUSB0 firmware/cnc
./run_web.sh                                  # then connect and HOME in the AOI screen
```

`arduino-cli` (user install, `~/.local/bin`) and the AVR core are set up on the station; the
Nano has the old bootloader (57600 baud, `cpu=atmega328old`). Needs the AccelStepper library
(`arduino-cli lib install AccelStepper`). A copy of the firmware that was on the Nano before
this version is in `~/firmware_backup/` on the Jetson.
