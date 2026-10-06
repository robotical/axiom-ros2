# Firmware alignment work

Scope: align the ROS repository with current Axiom/Raft firmware and close the
integration gaps identified on 2026-09-29. Firmware repositories remain read-only.

Completion requires evidence for every item below, not just passing decoder tests.

- [x] Versioned devjson envelopes, numeric/legacy type discovery, per-device metadata.
- [x] FIFO and ordinary decoding, signed/scaled values, validity, array semantics, SI units.
- [x] Device timestamps, FIFO sample timing, wrap/gap/reboot and ROS clock handling.
- [x] Device registry, hot-plug/deletion, metadata invalidation, bounded pending data.
- [x] Unified request correlation/cancellation and serial/WS session lifecycle.
- [x] Readiness, reconnect/resubscription, concurrent RPCs and responsive shutdown.
- [x] Acknowledged subscriptions, separate sample-rate configuration and real RTT.
- [x] Collision-free topics, per-sensor frames, standard/custom ROS adapters and QoS.
- [x] Diagnostics for unsupported formats, errors, stale data, drops and stream ownership.
- [x] Bringup/configuration, dependency declarations, installation, tools and documentation.
- [x] Protocol/firmware fixture tests, fake-device transport integration and real ROS tests.
- [x] Clean ROS build/test in Docker; inspect coverage against all requirements.

Firmware fan-out cannot be fixed solely in this repository. The bridge must own one
upstream acquisition subscription and distribute to ROS consumers; document and
diagnose the upstream limitation. Full actuator control via ros2_control is a separate
feature, not a requirement of this sensor bridge update.

Baseline: ROS 06561e0; Axiom 0941576; RaftCore 9594620; RaftI2C 1f2eeef.
RaftSysMods inspected at a1af7f1 differs from Axiom's pin 88512b7. Integration
fixtures must document the source revision rather than assert deployed compatibility.

## Completion evidence

- Clean ROS Jazzy Docker build: all six packages passed.
- Tests cover firmware fixtures, real WebSocket and POSIX serial peers, real ROS DDS,
  services, reconnect, launch/shutdown and package lint. See [validation](validation.md).
- [Driver contracts](../src/axiom_driver/README.md) and
  [migration/firmware limits](firmware-alignment.md) document the changed public API.
- Firmware fan-out remains an upstream constraint, mitigated here by one acquisition
  owner plus DDS fan-out. Hardware timing/performance and exact flashed revision
  verification remain explicitly unverified, not hidden behind passing fake-peer tests.
- Final test result: **67 tests, 0 errors, 0 failures, 4 pre-existing copyright skips**.
  Installed launch with JSON frame/QoS overrides and SIGINT shutdown passed.
