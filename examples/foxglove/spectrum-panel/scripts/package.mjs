import { readFile, writeFile } from "node:fs/promises";
import { strToU8, zipSync } from "fflate";

const manifest = JSON.parse(await readFile("package.json", "utf8"));
const files = {};
for (const name of ["package.json", "README.md", "CHANGELOG.md", "dist/extension.js"]) {
  files[name] = strToU8(await readFile(name, "utf8"));
}
const filename = `dist/${manifest.publisher}.${manifest.name}-${manifest.version}.foxe`;
await writeFile(filename, zipSync(files));
console.log(filename);
