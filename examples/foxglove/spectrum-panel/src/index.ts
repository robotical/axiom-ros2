import type { ExtensionContext } from "@foxglove/extension";
import { initSpectrumPanel } from "./panel.ts";

export function activate(extensionContext: ExtensionContext): void {
  extensionContext.registerPanel({ name: "Axiom Spectrum", initPanel: initSpectrumPanel });
}
