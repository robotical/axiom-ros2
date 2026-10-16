// Run with Node.js 24+: node --test examples/foxglove/test_sound_demo.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import spectrum, { inputs, output } from "./sound-spectrum.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const layout = JSON.parse(read("./one-axiom-sound.json"));
const catalogue = JSON.parse(read("../../src/axiom_driver/test/fixtures/firmware_catalogue.json"));
const attributes = catalogue.records.RoboticalSoundSensor.resp.a;
const levels = [38, 37, 31, 36, 31, 30, 25, 24, 20];

function event(bands = { value: levels, unit: "dB", valid: true }) {
  return {
    topic: inputs[0],
    message: {
      header: { stamp: { sec: 123, nsec: 456 }, frame_id: "sound_sensor" },
      device_type: "RoboticalSoundSensor",
      values_json: JSON.stringify({ bands }),
    },
  };
}

test("layout embeds the standalone script and plots its output in array-index mode", () => {
  const scripts = Object.values(layout.userNodes);
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].sourceCode, read("./sound-spectrum.ts"));
  const panel = layout.configById["Plot!axiom1soundspectrum"];
  assert.equal(panel.xAxisVal, "index");
  assert.equal(panel.isSynced, false);
  assert.equal(panel.paths[0].value, `${output}.bands_db[:]`);
});

test("layout covers every scalar from the actual descriptor using the configured aliases", () => {
  const expected = attributes.filter((attr) => attr.n !== "bands").map((attr) => attr.n).sort();
  const plots = Object.values(layout.configById).filter((panel) => panel.xAxisVal === "timestamp");
  const actual = plots.flatMap((panel) => panel.paths.map((path) => {
    assert.ok(path.value.startsWith("/axiom1/sound/"));
    assert.ok(path.value.endsWith(".data"));
    return path.value.slice("/axiom1/sound/".length, -".data".length);
  })).sort();
  assert.deepEqual(actual, expected);
  for (const panel of plots) {
    assert.equal(panel.followingViewWidth, 30);
    assert.ok(panel.paths.every((path) => path.timestampMethod === "receiveTime"));
  }
});

test("all configured panels occur exactly once in the layout", () => {
  function leaves(node) {
    return typeof node === "string" ? [node] : [...leaves(node.first), ...leaves(node.second)];
  }
  assert.deepEqual(leaves(layout.layout).sort(), Object.keys(layout.configById).sort());
});

test("screenshot values retain their dB scale, sample header and descriptor frequency order", () => {
  const input = event();
  const result = spectrum(input);
  assert.deepEqual(result.bands_db, levels);
  assert.deepEqual(result.header, input.message.header);
  const bandDescriptor = attributes.find((attr) => attr.n === "bands");
  const frequencies = bandDescriptor.el.map((label) =>
    label.endsWith("k") ? Number(label.slice(0, -1)) * 1000 : Number(label),
  );
  assert.deepEqual(result.frequency_hz, frequencies);
  assert.deepEqual(JSON.parse(input.message.values_json).bands.value, levels);
});

test("negative engineering levels are not offset or clipped", () => {
  const values = [-100, -45.5, -1, 0, 1, 30, 40, 100, 155];
  assert.deepEqual(spectrum(event({ value: values, unit: "dB", valid: true })).bands_db, values);
});

test("invalid/null/nonnumeric bins become gaps rather than false zero readings", () => {
  const input = event({ value: [null, "42", ...levels.slice(2)], unit: "dB", valid: true });
  const result = spectrum(input);
  assert.ok(Number.isNaN(result.bands_db[0]));
  assert.ok(Number.isNaN(result.bands_db[1]));
  assert.deepEqual(result.bands_db.slice(2), levels.slice(2));
  assert.ok(spectrum(event({ value: levels, unit: "dB", valid: false })).bands_db.every(Number.isNaN));
  const flags = [false, ...Array(8).fill(true)];
  const masked = spectrum(event({ value: levels, unit: "dB", valid: flags }));
  assert.ok(Number.isNaN(masked.bands_db[0]));
  assert.deepEqual(masked.bands_db.slice(1), levels.slice(1));
});

test("malformed JSON and unsupported band shapes/units are skipped without throwing", () => {
  for (const json of ["{", "null", "{}", "[]", '"text"']) {
    const input = event();
    input.message.values_json = json;
    assert.equal(spectrum(input), undefined);
  }
  for (const bands of [
    { value: levels.slice(1), unit: "dB" },
    { value: [...levels, 0], unit: "dB" },
    { value: "38,37", unit: "dB" },
    { value: levels, unit: "dBA" },
    { value: levels, unit: "dB", valid: [true] },
  ]) {
    assert.equal(spectrum(event(bands)), undefined);
  }
});

test("another sensor is rejected and subsequent valid messages recover without retained state", () => {
  const input = event();
  input.message.device_type = "AMG8833";
  assert.equal(spectrum(input), undefined);
  const result = spectrum(event());
  result.frequency_hz[0] = 999;
  result.bands_db[0] = 999;
  assert.equal(spectrum(event()).frequency_hz[0], 31.5);
  assert.deepEqual(spectrum(event()).bands_db, levels);
});
