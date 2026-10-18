import assert from "node:assert/strict";
import test from "node:test";
import { parseHTML } from "linkedom";
import { initSpectrumPanel } from "../src/panel.ts";
import { descriptor, levels, sample } from "./fixtures.mjs";

function setup(initialState) {
  const { document, window } = parseHTML("<html><body><div id='panel'></div></body></html>");
  const subscriptions = [], saved = [], watched = [];
  const context = {
    panelElement: document.getElementById("panel"), initialState,
    subscribe: (topics) => subscriptions.push(topics), saveState: (state) => saved.push(state),
    watch: (field) => watched.push(field), updatePanelSettingsEditor: (state) => { context.settings = state; },
  };
  const dispose = initSpectrumPanel(context);
  let completed = 0;
  const render = (state) => context.onRender(state, () => { completed++; });
  return { context, document, window, subscriptions, saved, watched, render, dispose, completed: () => completed };
}
const topic = "/axiom1/sound/sample";
function event(message = sample(), inputTopic = topic, sec = 123) {
  return { topic: inputTopic, receiveTime: { sec, nsec: 0 }, message };
}

test("Foxglove rendering produces labelled, differently coloured bars and acknowledges frames", () => {
  const panel = setup();
  panel.render({ currentFrame: [event()], currentTime: { sec: 123, nsec: 0 }, colorScheme: "dark" });
  const bars = [...panel.document.querySelectorAll(".bar")];
  assert.equal(bars.length, 9);
  assert.equal(new Set(bars.map((bar) => bar.getAttribute("fill"))).size, 9);
  assert.deepEqual([...panel.document.querySelectorAll(".label")].map((node) => node.textContent), descriptor.el);
  assert.equal(panel.document.querySelector(".axiom-spectrum").dataset.theme, "dark");
  assert.equal(panel.completed(), 1);
  assert.ok(panel.watched.includes("currentFrame"));
  panel.dispose();
});

test("last sample in the frame wins and unrelated topics cannot change the display", () => {
  const panel = setup();
  panel.render({ currentFrame: [event(), event(sample(Array(9).fill(60))), event(sample(Array(9).fill(99)), "/other/sample")] });
  assert.ok([...panel.document.querySelectorAll(".value")].every((node) => node.textContent === "60.0"));
  panel.dispose();
});

test("invalid bins have no bar and malformed messages clear previous data, then recover", () => {
  const panel = setup();
  panel.render({ currentFrame: [event(sample(levels, [false, ...Array(8).fill(true)]))] });
  assert.equal(panel.document.querySelectorAll(".bar").length, 8);
  assert.equal(panel.document.querySelector(".value").textContent, "—");
  panel.render({ currentFrame: [event({ ...sample(), values_json: "{" })] });
  assert.equal(panel.document.querySelectorAll(".bar").length, 0);
  assert.match(panel.document.querySelector(".message").textContent, /malformed/);
  panel.render({ currentFrame: [event()] });
  assert.equal(panel.document.querySelectorAll(".bar").length, 9);
  assert.equal(panel.completed(), 3);
  panel.dispose();
});

test("topic selection resets displayed readings, persists state and changes the subscription", () => {
  const panel = setup({ topic, minDb: -100, maxDb: 155 });
  panel.render({ topics: [
    { name: "/robot/sound/sample", schemaName: "axiom_interfaces/msg/DeviceSample" },
    { name: "/imu", schemaName: "sensor_msgs/msg/Imu" }], currentFrame: [event()] });
  const select = panel.document.querySelector("select");
  assert.equal(select.options.length, 2);
  select.options[0].selected = false;
  select.options[1].selected = true;
  select.dispatchEvent(new panel.window.Event("change"));
  assert.equal(panel.saved.at(-1).topic, "/robot/sound/sample");
  assert.equal(panel.saved.at(-1).minDb, -100);
  assert.deepEqual(panel.subscriptions.at(-1), [{ topic: "/robot/sound/sample" }]);
  assert.equal(panel.document.querySelectorAll(".bar").length, 0);
  panel.dispose();
});

test("settings persist valid scales and preserve actual values when their bars are clipped", () => {
  const panel = setup();
  panel.render({ currentFrame: [event(sample([-80, 130, ...levels.slice(2)]))] });
  assert.equal(panel.document.querySelectorAll(".value")[0].textContent, "-80.0");
  assert.equal(panel.document.querySelectorAll(".value")[1].textContent, "130.0");
  const update = (field, value) => panel.context.settings.actionHandler({ action: "update", payload: { path: ["spectrum", field], value } });
  update("maxDb", 155);
  update("minDb", -100);
  assert.equal(panel.saved.at(-1).minDb, -100);
  const count = panel.saved.length;
  update("minDb", 200);
  assert.equal(panel.saved.length, count);
  panel.dispose();
});

test("old timeline data is marked stale; a seek clears it and a new sample recovers", () => {
  const panel = setup();
  panel.render({ currentFrame: [event()], currentTime: { sec: 123, nsec: 0 } });
  panel.render({ currentTime: { sec: 130, nsec: 0 } });
  assert.match(panel.document.querySelector(".badge").textContent, /Stale/);
  panel.render({ didSeek: true, currentTime: { sec: 100, nsec: 0 } });
  assert.equal(panel.document.querySelectorAll(".bar").length, 0);
  panel.render({ currentFrame: [event(sample(), topic, 101)], currentTime: { sec: 101, nsec: 0 } });
  assert.equal(panel.document.querySelector(".badge").textContent, "Latest sample");
  panel.dispose();
});

test("descriptor labels render as text and cleanup removes DOM and subscriptions", () => {
  const panel = setup();
  const meta = { ...descriptor, el: ["<img src=x onerror=alert(1)>", ...descriptor.el.slice(1)] };
  panel.render({ currentFrame: [event(sample(levels, true, meta))] });
  assert.equal(panel.document.querySelector("img"), null);
  assert.equal(panel.document.querySelector(".label").textContent, meta.el[0]);
  panel.dispose();
  assert.equal(panel.context.panelElement.children.length, 0);
  assert.equal(panel.context.onRender, undefined);
  assert.deepEqual(panel.subscriptions.at(-1), []);
});
