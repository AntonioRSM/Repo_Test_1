// Rebuilds dist/ when any UI source is newer than the last build, so start.cmd never
// launches a stale interface after a git pull or a code change.
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const root = path.join(__dirname, "..");
const built = path.join(root, "dist", "index.html");
const inputs = ["src", "index.html", "package.json", "tsconfig.json", "vite.config.ts"];

function newest(p) {
  if (!fs.existsSync(p)) return 0;
  const stat = fs.statSync(p);
  if (!stat.isDirectory()) return stat.mtimeMs;
  return Math.max(0, ...fs.readdirSync(p).map((name) => newest(path.join(p, name))));
}

const builtAt = fs.existsSync(built) ? fs.statSync(built).mtimeMs : 0;
const changedAt = Math.max(...inputs.map((p) => newest(path.join(root, p))));
if (changedAt > builtAt) {
  console.log(builtAt ? "Interfaccia modificata: ricompilo..." : "Prima compilazione dell'interfaccia...");
  execSync("npm run build", { cwd: root, stdio: "inherit" });
}
