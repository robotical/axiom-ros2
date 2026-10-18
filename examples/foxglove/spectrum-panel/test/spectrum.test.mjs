import assert from "node:assert/strict";
import test from "node:test";
import { barFraction, DEFAULT_CONFIG, parseSample, readConfig } from "../src/spectrum.ts";
import { descriptor, levels, sample } from "./fixtures.mjs";


test("actual descriptor labels and engineering readings are retained without offsetting", () => {
  const { spectrum } = parseSample(sample());
  assert.deepEqual(spectrum.bands.map((band) => band.label), descriptor.el);
  assert.deepEqual(spectrum.bands.map((band) => band.db), levels);
  assert.equal(spectrum.frame, "dummy_sound_sensor");
});

test("different descriptor band counts and frequency labels are supported", () => {
  const { spectrum } = parseSample(sample([3, 5, 9], true, { el: [80, "400", "2k"], eu: "Hz" }));
  assert.deepEqual(spectrum.bands, [{ label: "80", db: 3 }, { label: "400", db: 5 }, { label: "2k", db: 9 }]);
});

test("invalid bands are omitted rather than turned into zero dB readings", () => {
  const flags = [false, ...Array(8).fill(true)];
  assert.equal(parseSample(sample(levels, flags)).spectrum.bands[0].db, null);
  assert.ok(parseSample(sample(levels, false)).spectrum.bands.every((band) => band.db === null));
  const value = [null, "42", ...levels.slice(2)];
  assert.deepEqual(parseSample(sample(value)).spectrum.bands.slice(0, 2).map((band) => band.db), [null, null]);
});

test("negative and out-of-scale values remain intact while drawing clips to the scale", () => {
  const { spectrum } = parseSample(sample([-80, 130, ...levels.slice(2)]));
  assert.equal(spectrum.bands[0].db, -80);
  assert.equal(spectrum.bands[1].db, 130);
  assert.equal(barFraction(-80, DEFAULT_CONFIG), 0);
  assert.equal(barFraction(130, DEFAULT_CONFIG), 1);
  assert.equal(barFraction(40, DEFAULT_CONFIG), .5);
});

test("bad envelopes and malformed JSON produce a useful error without throwing", () => {
  for (const value of [null, false, [], {}, { device_type: "AMG8833" },
    { ...sample(), values_json: "{" }, { ...sample(), values_json: "null" }]) {
    assert.equal(typeof parseSample(value).error, "string");
  }
});

test("missing frequency metadata, wrong units, invalid shapes and bad validity are rejected", () => {
  const entries = [
    { value: levels, unit: "dBA", meta: descriptor },
    { value: [], unit: "dB", meta: descriptor },
    { value: Array(65).fill(0), unit: "dB", meta: { el: Array(65).fill("1k"), eu: "Hz" } },
    { value: levels, unit: "dB" },
    { value: levels, unit: "dB", meta: { el: descriptor.el, eu: "index" } },
    { value: levels, unit: "dB", meta: { el: ["1k"], eu: "Hz" } },
    { value: levels, unit: "dB", meta: descriptor, valid: [true] },
    { value: levels, unit: "dB", meta: descriptor, valid: "true" },
  ];
  for (const bands of entries) {
    assert.equal(typeof parseSample({ ...sample(), values_json: JSON.stringify({ bands }) }).error, "string");
  }
});

test("configuration rejects broken scales without losing the chosen topic", () => {
  assert.deepEqual(readConfig(undefined), DEFAULT_CONFIG);
  assert.deepEqual(readConfig({ topic: "/robot/sound/sample", minDb: 100, maxDb: 20 }),
    { ...DEFAULT_CONFIG, topic: "/robot/sound/sample" });
  assert.deepEqual(readConfig({ topic: "relative", minDb: -100, maxDb: 155 }),
    { ...DEFAULT_CONFIG, minDb: -100, maxDb: 155 });
});
