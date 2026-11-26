"""Offline checks of the Settings script: a pending edit while a save is in
flight, a page that cannot save, and the keys the script never spells."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SETTINGS_SCRIPT = Path(__file__).resolve().parents[1] / "webapp/static/settings.js"

#: The start of each harness: the page data, ``settings``, and a stand-in for
#: the DOM that the Settings script reads. ``__PAGE__`` is the page data that a
#: test sets over the data here.
_DOM = r"""
const fs = require("fs");
const assert = require("assert");
class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.textContent = "";
    this.value = ""; this.hidden = false; this.disabled = false; this.listeners = {};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
}
const rows = [
  { key: "tiers.base.vendor", group: "Models", label: "Base vendor", value: "anthropic",
    shipped: "anthropic", source: "page", source_text: "this page", mark: "changes", options: ["anthropic", "openai"] },
  { key: "credentials.anthropic.api_key", group: "Credentials", label: "Anthropic API key",
    value: null, shipped: null, source: "page", source_text: "this page", mark: "changes", secret: true,
    key_saved: false, vendor: "anthropic", modes: ["api_key"] },
];
const settings = { revision: "one", rows, modes: { anthropic: ["api_key"], openai: ["api_key"] },
  vendor_rows: ["tiers.base.vendor"], override_vendors: [], nodes: { file: null, refusal: null, rows: [] }, models: {}, iam: [], unknown: [], settings_file: "settings.env",
  error: null, settings_file_refusal: null, ...__PAGE__ };
const ids = Object.fromEntries([
  "settings", "settings-rows", "model-lists", "settings-search", "changes-list",
  "changes-panel", "changes-column", "save-changes", "discard-changes", "save-errors", "save-status",
  "engine-error", "unknown-lines", "settings-file",
].map((id) => [id, new Node(id)]));
ids.settings.textContent = JSON.stringify(settings);
const layout = new Node("layout");
globalThis.Node = Node;
globalThis.document = {
  getElementById: (id) => ids[id],
  querySelector: () => layout,
  createElement: (tag) => new Node(tag),
  createTextNode: (text) => { const item = new Node("text"); item.textContent = text; return item; },
};
// A string child stands for the text node that a real append makes of it.
const text = (entry) =>
  typeof entry === "string" ? entry : entry.textContent + entry.children.map(text).join("");
const scriptText = process.argv.slice(1).map((file) => fs.readFileSync(file, "utf8")).join("\n");
"""


def _run(body: str, page: str = "{}") -> None:
    """Run ``body`` in node after :data:`_DOM`, with ``page`` over the page
    data, and fail on a failed assert."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is needed to run the Settings script")
    harness = _DOM.replace("__PAGE__", page) + body
    result = subprocess.run(
        [
            node,
            "-e",
            harness,
            str(SETTINGS_SCRIPT.with_name("service_answer.js")),
            str(SETTINGS_SCRIPT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_inactive_edit_stays_visible_and_pending_after_save():
    _run(r"""
let resolveSave;
let sent;
globalThis.fetch = (_url, request) => {
  sent = JSON.parse(request.body);
  return new Promise((resolve) => { resolveSave = resolve; });
};
eval(scriptText + `
(async () => {
  assert.strictEqual(document.getElementById("changes-column").hidden, true);
  change(rowOf("credentials.anthropic.api_key"), "private-key");
  change(rowOf("tiers.base.vendor"), "openai");
  assert.strictEqual(document.getElementById("changes-column").hidden, false);
  const item = document.getElementById("changes-list").children.find(
    (entry) => entry["data-key"] === "credentials.anthropic.api_key");
  assert(item);
  assert(text(item).includes("stays pending"));
  assert(!text(item).includes("private-key"));
  const restartHint = (row) => notes(row).some((note) => note && text(note).includes("after a restart"));
  assert.strictEqual(restartHint({ ...rowOf("tiers.base.vendor"), store: true }), true);
  assert.strictEqual(restartHint(rowOf("tiers.base.vendor")), false);
  const pendingSave = save();
  assert.strictEqual(layout.inert, true);
  assert.strictEqual(document.getElementById("unknown-lines").inert, true);
  assert.strictEqual(document.getElementById("save-changes").disabled, true);
  assert.deepStrictEqual(sent.changes, { "tiers.base.vendor": "openai" });
  resolveSave({ ok: true, json: async () => ({ settings: {
    ...${JSON.stringify(settings)}, revision: "two", rows: ${JSON.stringify(rows)}.map((row) =>
      row.key === "tiers.base.vendor" ? { ...row, value: "openai" } : row),
  }, restart: [] }) });
  await pendingSave;
  assert.strictEqual(layout.inert, false);
  assert.strictEqual(changes.has("tiers.base.vendor"), false);
  assert.strictEqual(changes.get("credentials.anthropic.api_key"), "private-key");
  assert.strictEqual(document.getElementById("changes-column").hidden, false);
  assert.strictEqual(document.getElementById("save-changes").disabled, true);
  assert.strictEqual(document.getElementById("discard-changes").disabled, false);
  discard();
  assert.strictEqual(document.getElementById("changes-column").hidden, true);
})().catch((error) => { console.error(error); process.exitCode = 1; });
`);
""")


@pytest.mark.parametrize(
    "error",
    [
        pytest.param("null", id="the engine runs"),
        pytest.param('"settings.env: mode 0775"', id="the engine did not start"),
    ],
)
def test_a_refused_settings_file_disables_the_save_and_names_the_refusal(error):
    """Where the app refuses ``settings.env``, no save can pass, so the page
    offers none and shows the refusal once, whether or not the engine runs."""
    _run(
        r"""
let sent = false;
globalThis.fetch = () => { sent = true; return new Promise(() => {}); };
eval(scriptText + `
change(rowOf("tiers.base.vendor"), "openai");
assert.strictEqual(document.getElementById("save-changes").disabled, true);
assert.strictEqual(document.getElementById("discard-changes").disabled, false);
const banner = document.getElementById("engine-error");
assert.strictEqual(banner.hidden, false);
assert(text(banner).includes("cannot save"));
assert.strictEqual(text(banner).split("settings.env: mode 0775").length, 2);
save();
assert.strictEqual(sent, false);
`);
""",
        page=f'{{ revision: null, error: {error}, settings_file_refusal: "settings.env: mode 0775" }}',
    )


def test_the_script_spells_no_tier_key():
    """The server states each thinking row's tier, the keys of its tier's
    vendor and model rows, and the keys of the tier vendor rows, so the script
    parses no ``sampling.`` or ``tiers.`` key and spells no ``tiers.`` key."""
    script = SETTINGS_SCRIPT.read_text()

    assert "sampling\\." not in script
    assert "tiers\\." not in script
    assert "`tiers.${" not in script
