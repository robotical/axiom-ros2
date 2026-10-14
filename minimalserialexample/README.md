# Legacy serial console prototype

For supported USB acquisition and ROS topics, follow the
[current host-driver setup](../README.md) and
[user guides](https://userguides.robotical.io/axiom/ros2/start).

This directory contains an earlier console experiment, rather than the ROS driver.
The existing `minimalserialconnection.py` opens the module-level `PORT` at `BAUD`,
sends an ASCII JSON subscription using `NAME` and `RATE`, and prints decoded console
lines from a background reader. Those constants would need to be adapted to the
actual device for a console experiment.

The script has no command-line port/rate options, Mini-HDLC or ProtocolOverAscii
frame decoder, ROS topics, acknowledgement checks or automatic resubscription.
The earlier descriptions of binary mode and related CLI flags did not describe
this file. Use `axiom_driver` for the current framed firmware contract.

Keep this prototype separate from an active driver, updater or other serial reader:
one application should own an Axiom serial connection at a time. Its console output
does not establish successful acquisition or correctly decoded sensor measurements.
