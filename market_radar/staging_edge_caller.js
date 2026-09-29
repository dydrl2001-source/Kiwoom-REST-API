const functionUrl = process.env.STAGING_FUNCTION_URL;
const publishableKey = process.env.STAGING_PUBLISHABLE_KEY;
const soakToken = process.env.STAGING_SOAK_TOKEN;
const intervalMs = Math.max(60_000, Number(process.env.STAGING_HEARTBEAT_SECONDS || "600") * 1000);

if (!functionUrl || !publishableKey || !soakToken) {
  throw new Error("staging runtime environment incomplete");
}

let consecutiveErrors = 0;

async function pulse() {
  const at = new Date().toISOString();
  try {
    const response = await fetch(functionUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "apikey": publishableKey,
        "x-soak-token": soakToken,
      },
      body: JSON.stringify({ source: "railway-encoder-staging-caller", invoked_at: at }),
    });
    const text = await response.text();
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${text.slice(0, 240)}`);
    consecutiveErrors = 0;
    console.log(JSON.stringify({ event: "staging_edge_pulse", at, status: response.status, body: text.slice(0, 400) }));
  } catch (error) {
    consecutiveErrors += 1;
    console.error(JSON.stringify({
      event: "staging_edge_pulse_error",
      at,
      consecutive_errors: consecutiveErrors,
      error: error instanceof Error ? error.message : String(error),
    }));
    if (consecutiveErrors >= 3) process.exit(2);
  }
}

await pulse();
setInterval(pulse, intervalMs);
