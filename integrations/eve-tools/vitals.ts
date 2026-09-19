// Vitals endpoint for the Daedalus infra health tracker (https://github.com/ArturSkrin/daedalus-infra-health).
//
// It gives the Daedalus collector what a Triage cluster agent would otherwise measure from outside:
//   - RED: cumulative request, error and duration counters for /api (the collector turns them into rates),
//   - USE: pressure stall information (PSI), memory and OOM kills, read from this container's own cgroup v2.
//     No privileges and no docker.sock are needed: a container may always read its own cgroup files.
//   - readiness of what the app depends on: its Postgres database.
//
// Wired in from server/index.ts, right after the body parsers.
//
// Set VITALS_TOKEN in .env to require the same token from the collector. Without it the endpoint is open,
// which is acceptable only while nginx does not proxy /internal/ to the outside (see integrations/eve-tools/README.md in the tracker repository).

import type { Express, NextFunction, Request, Response } from "express";
import { readFileSync } from "fs";
import { sql } from "drizzle-orm";
import { db } from "./db";

const BUCKETS_MS = [50, 100, 250, 500, 1000, 2500, 5000, 10000];
const DB_TIMEOUT_MS = 2000;

const startedAtUnix = Math.floor(Date.now() / 1000);
let requests = 0;
let errors = 0;
// cumulative histogram, Prometheus style: every bucket counts requests at or under its bound
const durationBucketsMs: Record<string, number> = { "+Inf": 0 };
for (const bound of BUCKETS_MS) durationBucketsMs[String(bound)] = 0;

export function vitalsMiddleware(req: Request, res: Response, next: NextFunction) {
  if (!req.path.startsWith("/api")) return next();
  const started = process.hrtime.bigint();
  res.on("finish", () => {
    const ms = Number(process.hrtime.bigint() - started) / 1e6;
    requests += 1;
    // a 4xx is the caller's mistake; only a 5xx means this service failed someone
    if (res.statusCode >= 500) errors += 1;
    for (const bound of BUCKETS_MS) if (ms <= bound) durationBucketsMs[String(bound)] += 1;
    durationBucketsMs["+Inf"] += 1;
  });
  next();
}

function readCgroup(file: string): string | null {
  try {
    return readFileSync(`/sys/fs/cgroup/${file}`, "utf8");
  } catch {
    return null; // not cgroup v2, or not Linux: reported as "not measured", never as zero
  }
}

// "some avg10=0.00 avg60=1.25 avg300=0.80 total=123": share of the last 60 s in which a task was stalled
function pressureAvg60(file: string): number | null {
  const match = readCgroup(file)?.match(/^some .*?avg60=([\d.]+)/m);
  return match ? Number(match[1]) : null;
}

function cgroup() {
  const current = Number(readCgroup("memory.current"));
  const max = readCgroup("memory.max")?.trim();
  const oom = readCgroup("memory.events")?.match(/^oom_kill (\d+)/m);
  return {
    cpuPressureAvg60: pressureAvg60("cpu.pressure"),
    memPressureAvg60: pressureAvg60("memory.pressure"),
    ioPressureAvg60: pressureAvg60("io.pressure"),
    memCurrentBytes: Number.isFinite(current) && current > 0 ? current : null,
    // "max" means the container has no memory limit, so there is nothing to be close to
    memMaxBytes: max && max !== "max" ? Number(max) : null,
    oomKills: oom ? Number(oom[1]) : null,
  };
}

async function checkDb(): Promise<{ ok: boolean; ms: number; error?: string }> {
  const started = Date.now();
  try {
    await Promise.race([
      db.execute(sql`select 1`),
      new Promise((_, reject) => setTimeout(() => reject(new Error(`no answer in ${DB_TIMEOUT_MS} ms`)), DB_TIMEOUT_MS)),
    ]);
    return { ok: true, ms: Date.now() - started };
  } catch (error) {
    return { ok: false, ms: Date.now() - started, error: error instanceof Error ? error.message : String(error) };
  }
}

// A request that came through a reverse proxy carries one of these. The collector calls the app directly over
// the Docker network and carries none, so anything forwarded from the outside gets a 404 even when nginx or an
// ingress proxies every path. This is a safety net, not a substitute for VITALS_TOKEN or a deny rule in nginx.
const PROXY_HEADERS = ["x-forwarded-for", "x-real-ip", "x-forwarded-host", "forwarded"];

export function registerVitals(app: Express) {
  app.get("/internal/vitals", async (req: Request, res: Response) => {
    if (PROXY_HEADERS.some((name) => req.header(name))) return res.status(404).end();
    const token = process.env.VITALS_TOKEN;
    if (token && req.header("x-vitals-token") !== token) return res.status(404).end();

    const database = await checkDb();
    res.json({
      startedAtUnix,
      ready: database.ok,
      requests,
      errors,
      durationBucketsMs,
      deps: { db: database },
      cgroup: cgroup(),
    });
  });
}
