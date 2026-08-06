import { startTunnel } from "untun";

async function main() {
  const tunnel = await startTunnel({
    url: "http://localhost:5173",
  });
  if (!tunnel) {
    console.error("Tunnel not started.");
    process.exit(1);
  }
  console.log("Waiting for tunnel URL...");
  const url = await tunnel.getURL();
  console.log("Tunnel ready at", url);
}

main().catch(console.error);
