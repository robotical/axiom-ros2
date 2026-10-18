import { build } from "esbuild";

await build({
  entryPoints: ["src/index.ts"], outfile: "dist/extension.js", bundle: true,
  platform: "browser", format: "cjs", target: "es2022", minify: true,
});
console.log("Built dist/extension.js");
