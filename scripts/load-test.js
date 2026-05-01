import http from "k6/http";
import { check, fail, sleep } from "k6";
import { Gauge, Rate } from "k6/metrics";

const serverErrorRate = new Rate("runbook_http_5xx_rate");
const pgbouncerPoolUtilization = new Gauge("runbook_pgbouncer_pool_utilization");

const baseUrl = (__ENV.RUNBOOK_API_BASE_URL || "http://localhost:8000").replace(
  /\/$/,
  "",
);
const orgId = __ENV.RUNBOOK_ORG_ID;
const email = __ENV.RUNBOOK_LOAD_TEST_EMAIL;
const password = __ENV.RUNBOOK_LOAD_TEST_PASSWORD;
const providedToken = __ENV.RUNBOOK_ACCESS_TOKEN;
const pgbouncerStatsUrl = __ENV.RUNBOOK_PGBOUNCER_STATS_URL;
const pgbouncerStatsToken = __ENV.RUNBOOK_PGBOUNCER_STATS_TOKEN;
const pgbouncerPoolSize = Number(__ENV.RUNBOOK_PGBOUNCER_POOL_SIZE || 0);

const thresholds = {
  "http_req_duration{endpoint:executions_list}": ["p(99)<200"],
  http_req_failed: ["rate<0.001"],
  runbook_http_5xx_rate: ["rate==0"],
};

if (pgbouncerStatsUrl) {
  thresholds.runbook_pgbouncer_pool_utilization = ["max<=1"];
}

export const options = {
  vus: Number(__ENV.RUNBOOK_LOAD_TEST_VUS || 50),
  duration: __ENV.RUNBOOK_LOAD_TEST_DURATION || "60s",
  thresholds,
};

export function setup() {
  if (!orgId) {
    fail("RUNBOOK_ORG_ID is required.");
  }

  if (
    pgbouncerStatsUrl &&
    (!Number.isFinite(pgbouncerPoolSize) || pgbouncerPoolSize <= 0)
  ) {
    fail(
      "RUNBOOK_PGBOUNCER_POOL_SIZE must be a positive number when RUNBOOK_PGBOUNCER_STATS_URL is set.",
    );
  }

  if (providedToken) {
    warmExecutionsList(providedToken);
    return { token: providedToken };
  }

  if (!email || !password) {
    fail(
      "Set RUNBOOK_ACCESS_TOKEN, or set RUNBOOK_LOAD_TEST_EMAIL and RUNBOOK_LOAD_TEST_PASSWORD.",
    );
  }

  const response = http.post(
    `${baseUrl}/api/v1/auth/login/`,
    JSON.stringify({ email, password }),
    {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "auth_login" },
    },
  );

  check(response, {
    "login succeeded": (res) => res.status === 200 && Boolean(res.json("access")),
  });

  if (response.status !== 200 || !response.json("access")) {
    fail(`Login failed with HTTP ${response.status}: ${response.body}`);
  }

  const token = response.json("access");
  warmExecutionsList(token);
  return { token };
}

function warmExecutionsList(token) {
  const response = http.get(`${baseUrl}/api/v1/executions/`, {
    headers: {
      Authorization: `Bearer ${token}`,
      "X-Organization-Id": orgId,
    },
    tags: { endpoint: "executions_list_warmup" },
  });
  check(response, {
    "executions list warmup returns 200": (res) => res.status === 200,
  });
  if (response.status !== 200) {
    fail(`Executions list warmup failed with HTTP ${response.status}: ${response.body}`);
  }
}

function observePgbouncerPool() {
  if (!pgbouncerStatsUrl) {
    return;
  }

  const headers = {};
  if (pgbouncerStatsToken) {
    headers.Authorization = `Bearer ${pgbouncerStatsToken}`;
  }

  const response = http.get(pgbouncerStatsUrl, { headers });
  const ok = check(response, {
    "pgbouncer stats endpoint returns 200": (res) => res.status === 200,
  });
  if (!ok) {
    pgbouncerPoolUtilization.add(2);
    return;
  }

  let activeConnections = response.json("server_connections");
  if (activeConnections === undefined || activeConnections === null) {
    activeConnections = response.json("active_server_connections");
  }
  if (activeConnections === undefined || activeConnections === null) {
    activeConnections = response.json("connections");
  }
  activeConnections = Number(activeConnections);
  const validConnectionCount =
    Number.isFinite(activeConnections) && activeConnections >= 0;
  check(response, {
    "pgbouncer stats include connection count": () => validConnectionCount,
  });

  pgbouncerPoolUtilization.add(
    validConnectionCount ? activeConnections / pgbouncerPoolSize : 2,
  );
}

export default function (data) {
  const response = http.get(`${baseUrl}/api/v1/executions/`, {
    headers: {
      Authorization: `Bearer ${data.token}`,
      "X-Organization-Id": orgId,
    },
    tags: { endpoint: "executions_list" },
  });

  serverErrorRate.add(response.status >= 500);

  check(response, {
    "executions list returns 200": (res) => res.status === 200,
    "executions list has no 5xx": (res) => res.status < 500,
  });

  observePgbouncerPool();
  sleep(1);
}
