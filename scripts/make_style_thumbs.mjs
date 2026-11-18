// Writes src/web/thumbs/<style>.webp: each resume style filled in with the demo person. The Create Resume
// preview shows these before a profile exists. Needs Playwright (global npm) and the repo's Python.
//     node scripts/make_style_thumbs.mjs [path/to/python]
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "src", "web", "thumbs");
const STYLES = ["executive", "navy_bar", "two_column", "structured", "genz"];
const PAGE = [816, 1056];
const THUMB = [572, 740];
const MAX_BYTES = 40 * 1024;
const DEMO_JSON = `
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, "src")
from jobomatic import demo, resume, store
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "jobomatic.db"
    demo.new_demo_database(db)
    conn = store.connect(db)
    print(json.dumps(resume.resume_data(conn, "Original")))
    conn.close()
`;

const npmRoot = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim();
const { chromium } = createRequire(join(npmRoot, "noop.js"))("playwright");
vm.runInThisContext(readFileSync(join(ROOT, "src", "web", "resume_render.js"), "utf8"));
const doc = JSON.parse(execFileSync(process.argv[2] || "python3", ["-c", DEMO_JSON], { cwd: ROOT, encoding: "utf8" }));
const templates = Object.fromEntries(STYLES.map((s) => [s, readFileSync(join(ROOT, "templates", `resume_${s}_v1.html`), "utf8")]));

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: PAGE[0], height: PAGE[1] } });
  for (const style of STYLES) {
    await page.setContent(globalThis.JOM.renderResume(doc, style, templates), { waitUntil: "load" });
    const png = (await page.screenshot()).toString("base64");
    const bytes = await page.evaluate(async ({ png, size, max }) => {
      const img = new Image();
      img.src = "data:image/png;base64," + png;
      await img.decode();
      const c = document.createElement("canvas");
      [c.width, c.height] = size;
      const g = c.getContext("2d");
      g.imageSmoothingQuality = "high";
      g.drawImage(img, 0, 0, size[0], size[1]);
      let b64 = "";
      for (const quality of [0.8, 0.7, 0.6, 0.5, 0.4]) {
        b64 = c.toDataURL("image/webp", quality).split(",")[1];
        if (b64.length * 3 / 4 <= max) break;
      }
      return b64;
    }, { png, size: THUMB, max: MAX_BYTES });
    const buf = Buffer.from(bytes, "base64");
    if (buf.length > MAX_BYTES || buf.subarray(8, 12).toString() !== "WEBP") throw new Error(`${style}: not a WebP under 40 KB`);
    writeFileSync(join(OUT, `${style}.webp`), buf);
    console.log(`${style}.webp ${buf.length} bytes`);
  }
  console.log(`✅ wrote ${STYLES.length} thumbnails to ${OUT}`);
} catch (err) {
  console.log(`❌ ${err.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
