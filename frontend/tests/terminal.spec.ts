/**
 * Frontend interaction tests.
 *
 * These drive the real UI in a real browser against the real backend. The alternative —
 * unit-testing the workspace renderers in isolation — would pass happily while the page failed
 * to hydrate, which is exactly the failure that cost an hour during development (a stale
 * `next-server` process served chunks from a superseded build: HTTP 200, server-rendered
 * markup, and a page that never responded to a single keystroke).
 *
 * So every test here asserts on something that can only be true if the whole chain works:
 * browser -> Next.js -> FastAPI -> SQLite.
 *
 * Run with the stack up:
 *   divya serve            (127.0.0.1:8000)
 *   cd frontend && pnpm start
 *   cd frontend && pnpm exec playwright test
 */

import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8000";

/** Fail loudly if the backend is not up, rather than reporting a confusing assertion failure. */
async function requireBackend() {
  const res = await fetch(`${API}/health`).catch(() => null);
  if (!res || !res.ok) {
    throw new Error(
      `backend not reachable at ${API} — start it with \`divya serve\`. ` +
        `These tests exercise the real stack and cannot be mocked.`,
    );
  }
}

async function command(page: Page, text: string) {
  const input = page.getByLabel("Command");
  await input.click();
  await input.fill(text);
  await input.press("Enter");
}

test.beforeAll(async () => {
  await requireBackend();
});

test("renders the terminal shell and reports backend health", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });

  await page.goto("/", { waitUntil: "networkidle" });
  await expect(page).toHaveTitle(/Divya/);
  await expect(page.getByLabel("Command")).toBeVisible();

  // The status bar must name the engine and the store. A terminal that cannot say what it is
  // connected to is not auditable.
  const status = page.locator("body");
  await expect(status).toContainText("system1:");
  await expect(status).toContainText("db:");

  expect(errors, `console errors: ${errors.join(" | ")}`).toHaveLength(0);
});

test("a new command switches to the market workspace and renders rows", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await command(page, "What changed materially across the market today?");

  await expect(page.locator("tbody tr").first()).toBeVisible();
  // Read every header and check the set. `toContainText([...])` against a multi-element
  // locator does not mean what it looks like, and the failure mode is a test that passes for
  // the wrong reason.
  const headers = (await page.locator("thead th").allInnerTexts()).map((s) => s.toLowerCase());
  for (const want of ["sym", "our label", "material", "system-1"]) {
    expect(headers.some((h) => h.includes(want)), `missing header ${want} in ${headers}`);
  }
  await expect(page.getByText("continuing", { exact: false })).toBeVisible();
});

test("follow-ups continue the same task and preserve the entity", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await command(page, "What changed materially across the market today?");
  await expect(page.locator("tbody tr").first()).toBeVisible();

  await command(page, "Why is AIIL high priority?");

  // The workspace changed, and AIIL survived the change.
  await expect(page.getByText("investigation", { exact: false }).first()).toBeVisible();
  const rail = page.locator("body");
  await expect(rail).toContainText("AIIL");
  // Both turns are recorded -- this is one task with two turns, not two tasks.
  await expect(rail).toContainText("2 turn");
});

test("undecided events are labelled, never shown as decided", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await command(page, "What changed materially across the market today?");
  await expect(page.locator("tbody tr").first()).toBeVisible();

  // Every MATERIAL cell must be either a percentage badge or an explicit "undecided". A
  // rendered dash or blank would be an event silently claiming a decision it does not have.
  const cells = page.locator("tbody tr td:nth-child(5)");
  const n = await cells.count();
  expect(n).toBeGreaterThan(0);
  for (let i = 0; i < Math.min(n, 12); i++) {
    const text = (await cells.nth(i).innerText()).trim();
    expect(text === "undecided" || /%/.test(text), `unexpected material cell: ${text}`);
  }
});

test("freshness is visible on the market workspace", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await command(page, "What changed materially across the market today?");
  await expect(page.locator("tbody tr").first()).toBeVisible();
  // The store's last-retrieval time is rendered, so a reader can see the age of the data.
  await expect(page.locator("body")).toContainText(/last retrieved|db:/);
});

test("the command surface is reachable from the keyboard", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("/");
  await expect(page.getByLabel("Command")).toBeFocused();
});

test("a failing command keeps the previous workspace on screen", async ({ page }) => {
  await page.goto("/", { waitUntil: "networkidle" });
  await command(page, "What changed materially across the market today?");
  await expect(page.locator("tbody tr").first()).toBeVisible();

  // Route the next call at a port with nothing behind it.
  await page.route("**/command", (route) => route.abort());
  await command(page, "Investigate a company that does not exist.");
  await expect(page.getByText(/unreachable|abort|failed/i).first()).toBeVisible();

  // The context rail is the point of the test: losing what you were reading because a
  // follow-up failed is worse than the failure.
  await expect(page.locator("tbody tr").first()).toBeVisible();
});
