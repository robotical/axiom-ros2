import { mkdir, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { McapWriter } from "@mcap/core";
import { sample } from "../test/fixtures.mjs";

const encoder = new TextEncoder();
const schema = { type: "object", properties: {
  device_type: { type: "string" }, values_json: { type: "string" },
  header: { type: "object", properties: {
    frame_id: { type: "string" }, stamp: { type: "object", properties: {
      sec: { type: "integer" }, nanosec: { type: "integer" },
    } },
  } },
} };

/** Synthetic engineering readings, not an audio recording or hardware capture. */
export async function makeRecording() {
  const chunks = [];
  let position = 0n;
  const writer = new McapWriter({ writable: {
    position: () => position,
    write: async (bytes) => { chunks.push(bytes.slice()); position += BigInt(bytes.byteLength); },
  } });
  await writer.start({ profile: "", library: "axiom-spectrum-synthetic-demo" });
  const schemaId = await writer.registerSchema({ name: "axiom_interfaces/msg/DeviceSample",
    encoding: "jsonschema", data: encoder.encode(JSON.stringify(schema)) });
  const channelId = await writer.registerChannel({ topic: "/axiom1/sound/sample", schemaId,
    messageEncoding: "json", metadata: new Map([["source", "SYNTHETIC DUMMY DATA"]]) });
  const base = 1792324800000000000n;
  for (let i = 0; i < 180; i++) {
    const sec = i / 4;
    const bass = sec >= 12 && sec < 24;
    const shape = bass ? [85, 78, 65, 48, 38, 32, 25, 20, 15] : [30, 38, 49, 63, 77, 72, 59, 44, 32];
    const values = shape.map((v, j) => Math.round((v + Math.sin(i * .18 + j * .7) * 4) * 10) / 10);
    const validity = sec >= 24 && sec < 28 ? [true, true, false, true, true, true, true, true, true]
      : !(sec >= 28 && sec < 32);
    const message = sample(values, validity);
    const time = base + BigInt(i) * 250000000n;
    message.header.stamp = { sec: Number(time / 1000000000n), nanosec: Number(time % 1000000000n) };
    if (sec >= 32 && sec < 36) message.values_json = "{";
    await writer.addMessage({ channelId, sequence: i, logTime: time, publishTime: time,
      data: encoder.encode(JSON.stringify(message)) });
  }
  await writer.end();
  return Buffer.concat(chunks);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  await mkdir("dist", { recursive: true });
  const data = await makeRecording();
  await writeFile("dist/axiom-spectrum-dummy.mcap", data);
  console.log(`dist/axiom-spectrum-dummy.mcap (${data.length} bytes; 45 seconds of dummy data)`);
}
