// Embedded in one-axiom-sound.json as the "Axiom sound spectrum" user script.
// These are already decoded engineering values: do not apply offsets again.
import type { Input, Message } from "./types.ts";

type Output = {
  header: Message<"std_msgs/msg/Header">;
  frequency_hz: number[];
  bands_db: number[];
};

type BandEntry = {
  value?: unknown;
  unit?: unknown;
  valid?: unknown;
};

export const inputs = ["/axiom1/sound/sample"];
export const output = "/foxglove_script/axiom1/sound/spectrum";

export default function script(event: Input<"/axiom1/sound/sample">): Output | undefined {
  if (event.message.device_type !== "RoboticalSoundSensor") {
    return undefined;
  }

  let values: { bands?: BandEntry } | null;
  try {
    values = JSON.parse(event.message.values_json);
  } catch {
    return undefined;
  }

  const bands = values?.bands;
  if (
    bands?.unit !== "dB" ||
    !Array.isArray(bands.value) ||
    bands.value.length !== 9 ||
    (Array.isArray(bands.valid) && bands.valid.length !== 9)
  ) {
    return undefined;
  }

  const validity = bands.valid;
  return {
    header: event.message.header,
    // Fixed order from the RoboticalSoundSensor descriptor's bands.el labels.
    frequency_hz: [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000],
    bands_db: bands.value.map((value, index) =>
      validity === false ||
      (Array.isArray(validity) && validity[index] !== true) ||
      typeof value !== "number" ||
      !Number.isFinite(value)
        ? NaN
        : value,
    ),
  };
}
