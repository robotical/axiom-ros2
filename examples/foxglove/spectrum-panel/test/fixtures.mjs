import { readFileSync } from "node:fs";
const catalogue = JSON.parse(readFileSync(new URL("../../../../src/axiom_driver/test/fixtures/firmware_catalogue.json", import.meta.url)));
export const descriptor = catalogue.records.RoboticalSoundSensor.resp.a.find((attr) => attr.n === "bands");
export const levels = [38, 37, 31, 36, 31, 30, 25, 24, 20];
export function sample(value = levels, valid = true, meta = descriptor) {
  return {
    device_type: "RoboticalSoundSensor",
    header: { stamp: { sec: 123, nanosec: 456 }, frame_id: "dummy_sound_sensor" },
    values_json: JSON.stringify({ bands: { value, unit: "dB", valid, meta } }),
  };
}
