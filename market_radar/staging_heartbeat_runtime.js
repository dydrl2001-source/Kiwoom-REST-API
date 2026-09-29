import { SQL } from "bun";

const url = process.env.DATABASE_URL;
const version = process.env.MARKET_RADAR_SCHEMA_VERSION || "2026.09.29.2";
const expectedChecksum = process.env.MARKET_RADAR_SCHEMA_CHECKSUM || "";
const intervalMs = Math.max(60_000, Number(process.env.STAGING_HEARTBEAT_SECONDS || "600") * 1000);

if (!url) throw new Error("DATABASE_URL missing");

const db = new SQL({
  url,
  max: 2,
  idleTimeout: 60,
  connectionTimeout: 15,
  maxLifetime: 3600,
});

let consecutiveErrors = 0;

async function pulse() {
  const now = new Date();
  try {
    const rows = await db`
      select version, checksum
      from public.market_radar_schema_migrations
      where version = ${version}
      limit 1
    `;
    const row = rows?.[0];
    const schemaOk = Boolean(row && row.version === version);
    const checksumOk = !expectedChecksum || row?.checksum === expectedChecksum;

    await db`
      insert into internal.staging_runtime_heartbeat(
        heartbeat_at, runtime_name, schema_version, schema_ok, checksum_ok
      )
      values(
        ${now}, 'railway-encoder-staging-runtime', ${version}, ${schemaOk}, ${checksumOk}
      )
      on conflict (heartbeat_at) do nothing
    `;

    consecutiveErrors = 0;
    console.log(JSON.stringify({
      event: "staging_runtime_heartbeat",
      at: now.toISOString(),
      schema_ok: schemaOk,
      checksum_ok: checksumOk,
      version,
    }));

    if (!schemaOk || !checksumOk) {
      throw new Error("schema version/checksum mismatch");
    }
  } catch (error) {
    consecutiveErrors += 1;
    console.error(JSON.stringify({
      event: "staging_runtime_error",
      at: now.toISOString(),
      consecutive_errors: consecutiveErrors,
      error: error instanceof Error ? error.message : String(error),
    }));
    if (consecutiveErrors >= 3) process.exit(2);
  }
}

await pulse();
setInterval(pulse, intervalMs);

process.on("SIGTERM", async () => {
  try { await db.close(); } catch {}
  process.exit(0);
});
