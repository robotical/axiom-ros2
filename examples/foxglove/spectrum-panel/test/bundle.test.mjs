import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";
import { build } from "esbuild";
import { parseHTML } from "linkedom";
import { sample } from "./fixtures.mjs";

test("the browser bundle registers the exported layout's panel and renders an existing DeviceSample", async () => {
  const output = await build({ entryPoints: ["src/index.ts"], bundle: true,
    platform: "browser", format: "cjs", target: "es2022", minify: true, write: false });
  const module = { exports: {} };
  runInNewContext(output.outputFiles[0].text, { module, exports: module.exports });
  let registered;
  module.exports.activate({ registerPanel: (panel) => { registered = panel; } });
  assert.equal(registered.name, "Axiom Spectrum");
  const manifest = JSON.parse(await readFile("package.json", "utf8"));
  const layout = JSON.parse(await readFile("one-axiom-spectrum.json", "utf8"));
  assert.ok(layout.layout.startsWith(`${manifest.name}.${registered.name}!`));
  const { document } = parseHTML("<html><body><div id='panel'></div></body></html>");
  const context = { panelElement: document.getElementById("panel"),
    initialState: layout.configById[layout.layout], subscribe: () => {},
    watch: () => {}, saveState: () => {}, updatePanelSettingsEditor: () => {} };
  const dispose = registered.initPanel(context);
  let completed = false;
  context.onRender({ currentFrame: [{ topic: "/axiom1/sound/sample", message: sample(),
    receiveTime: { sec: 1, nsec: 0 } }] }, () => { completed = true; });
  assert.equal(document.querySelectorAll(".bar").length, 9);
  assert.equal(completed, true);
  dispose();
});
