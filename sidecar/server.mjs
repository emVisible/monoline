// Monoline render sidecar — a thin wrapper around HyperFrames' producer HTTP server.
// Python spawns this with an explicit node 22 + SIDECAR_PORT + a shared token.
// It holds NO durable state: if it dies, the Python job row is the source of truth.
import { startServer } from "@hyperframes/producer/server";

function arg(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i > -1 ? process.argv[i + 1] : fallback;
}

const port = Number(arg("--port", process.env.SIDECAR_PORT || 8790));
const maxConcurrentRenders = Number(process.env.SIDECAR_MAX_CONCURRENT || 1);
const rendersDir = process.env.HYPERFRAMES_RENDERS_DIR || undefined;

// The separate health-probe worker thread is for k8s; disable it locally to avoid
// the (harmless) "could not resolve worker entry" noise. Main /health still works.
process.env.PRODUCER_DISABLE_HEALTH_WORKER ??= "1";

try {
  await startServer({ port, maxConcurrentRenders, rendersDir });
  console.log(`[monoline-sidecar] producer server listening on 127.0.0.1:${port} (max=${maxConcurrentRenders})`);
} catch (err) {
  console.error(`[monoline-sidecar] failed to start: ${err?.message || err}`);
  process.exit(1);
}
