import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const app = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
const api = readFileSync(new URL("../web/api.js", import.meta.url), "utf8");
const login = readFileSync(new URL("../web/screens/login.js", import.meta.url), "utf8");
const frontend = `${login}\n${app}`;

function requiresIds(...ids) {
  for (const id of ids) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
    assert.match(frontend, new RegExp(`getElementById\\(["']${id}["']\\)`));
  }
}

test("login flow keeps its browser and API contract", () => {
  requiresIds("login-screen", "login-form", "login-username", "login-password", "login-submit");
  assert.match(api, /authStatus\(\)/);
  assert.match(api, /authLogin\(username, password\)/);
});

test("detail, queue, and settings screens remain wired", () => {
  requiresIds("fp-detail-modal", "fp-detail-title", "fp-detail-add");
  requiresIds("queue-drawer", "queue-list", "queue-count");
  requiresIds("settings-btn");
  assert.match(html, /id=["']settings-general["']/);
  assert.match(html, /id=["']settings-system["']/);
  assert.match(app, /data-settings-target/);
  assert.match(api, /queueGet\(\)/);
  assert.match(api, /queueAdd\(slugs/);
  assert.match(api, /configGet\(\)/);
});
