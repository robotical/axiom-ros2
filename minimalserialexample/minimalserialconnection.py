#!/usr/bin/env python3
import serial, sys, threading

PORT = "/dev/cu.usbmodem2101"
BAUD = 115200
NAME = "devjson"
RATE = 5.0

def reader(ser):
    while True:
        try:
            line = ser.readline()
            if line:
                print("<<", line.decode("utf-8", "replace").rstrip())
        except Exception as e:
            print(f"[read error] {e}", file=sys.stderr)
            break

def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        print(f"[open error] {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Connected: {PORT} @ {BAUD}")

    threading.Thread(target=reader, args=(ser,), daemon=True).start()
    # cmd = f"subscription?action=update&name={NAME}&rateHz={RATE}\n"
    cmd = f'{{"cmdName":"subscription","action":"update","pubRecs":[{{"name":"{NAME}","trigger":"timeorchange","rateHz":{RATE}}}]}}\n'
    ser.write(cmd.encode())
    print(f">> {cmd.strip()}")

    try:
        while True: pass
    except KeyboardInterrupt:
        ser.close()

if __name__ == "__main__":
    main()
