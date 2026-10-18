import assert from "node:assert/strict";
import test from "node:test";
import { McapStreamReader } from "@mcap/core";
import { makeRecording } from "../demo/make-recording.mjs";
import { parseSample } from "../src/spectrum.ts";

test("dummy MCAP is complete and exercises parsing, invalid states and recovery", async () => {
  const reader = new McapStreamReader();
  reader.append(await makeRecording());
  const messages = [];
  let synthetic = false;
  for (let record; (record = reader.nextRecord());) {
    if (record.type === "Channel") synthetic ||= record.metadata.get("source") === "SYNTHETIC DUMMY DATA";
    if (record.type === "Message") messages.push(JSON.parse(new TextDecoder().decode(record.data)));
  }
  assert.equal(reader.done(), true);
  assert.equal(synthetic, true);
  assert.equal(messages.length, 180);
  assert.equal(parseSample(messages[0]).spectrum.bands.length, 9);
  assert.equal(parseSample(messages[100]).spectrum.bands[2].db, null);
  assert.ok(parseSample(messages[120]).spectrum.bands.every((band) => band.db === null));
  assert.match(parseSample(messages[132]).error, /malformed/);
  assert.equal(parseSample(messages[160]).spectrum.bands.length, 9);
});
