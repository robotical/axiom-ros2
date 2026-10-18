/** Decode existing DeviceSample data; engineering transforms already happened on the host. */
export type Band = { label: string; db: number | null };
export type Spectrum = { bands: Band[]; frame: string };
export type Result = { spectrum: Spectrum; error?: never } | { error: string; spectrum?: never };
export type Config = { topic: string; minDb: number; maxDb: number };
export const DEFAULT_CONFIG: Config = { topic: "/axiom1/sound/sample", minDb: -20, maxDb: 100 };

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

export function readConfig(value: unknown): Config {
  const state = record(value);
  const topic = typeof state?.topic === "string" && state.topic.startsWith("/")
    ? state.topic : DEFAULT_CONFIG.topic;
  const minDb = typeof state?.minDb === "number" && Number.isFinite(state.minDb)
    ? state.minDb : DEFAULT_CONFIG.minDb;
  const maxDb = typeof state?.maxDb === "number" && Number.isFinite(state.maxDb)
    ? state.maxDb : DEFAULT_CONFIG.maxDb;
  return maxDb > minDb ? { topic, minDb, maxDb } : { ...DEFAULT_CONFIG, topic };
}

export function parseSample(message: unknown): Result {
  const sample = record(message);
  if (sample?.device_type !== "RoboticalSoundSensor") {
    return { error: "Select a Robotical Sound Sensor sample topic." };
  }
  let values: unknown;
  try {
    if (typeof sample.values_json !== "string") {
      return { error: "The sample has no values_json string." };
    }
    values = JSON.parse(sample.values_json);
  } catch {
    return { error: "The sample contains malformed JSON." };
  }
  const bands = record(record(values)?.bands);
  if (bands?.unit !== "dB" || !Array.isArray(bands.value)
      || bands.value.length === 0 || bands.value.length > 64) {
    return { error: "Expected a non-empty bands.value array in dB." };
  }
  const meta = record(bands.meta);
  const labels = meta?.el;
  if (meta?.eu !== "Hz" || !Array.isArray(labels) || labels.length !== bands.value.length
      || !labels.every((label) => (typeof label === "string" && label.trim() !== "")
        || (typeof label === "number" && Number.isFinite(label)))) {
    return { error: "Frequency labels are missing from bands.meta.el." };
  }
  const validity = bands.valid;
  if (validity !== undefined && typeof validity !== "boolean"
      && (!Array.isArray(validity) || validity.length !== bands.value.length
        || !validity.every((flag) => typeof flag === "boolean"))) {
    return { error: "The band validity flags do not match the readings." };
  }
  const header = record(sample.header);
  return {
    spectrum: {
      frame: typeof header?.frame_id === "string" ? header.frame_id : "",
      bands: bands.value.map((value: unknown, index: number) => ({
        label: String(labels[index]),
        db: validity !== false && (!Array.isArray(validity) || validity[index] === true)
          && typeof value === "number" && Number.isFinite(value) ? value : null,
      })),
    },
  };
}

/** Clip drawing coordinates only, preserving the displayed measurement. */
export function barFraction(db: number, config: Config): number {
  return Math.max(0, Math.min(1, (db - config.minDb) / (config.maxDb - config.minDb)));
}

export function bandColor(index: number, count: number): string {
  const hue = 187 + (index / Math.max(1, count - 1)) * 102;
  return `hsl(${hue.toFixed(0)} 78% 59%)`;
}
