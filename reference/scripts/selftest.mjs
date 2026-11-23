// Offline self-test of the screening logic (no API keys needed): npm test
import assert from "node:assert/strict";
import { extractJSON, mergeScore, screenHolding, buildScreenPrompt } from "../lib/screening.mjs";

// 1. JSON extraction tolerates prose and fences
assert.deepEqual(extractJSON('Here you go:\n```json\n{"a":1,"b":{"c":2}}\n```'), { a: 1, b: { c: 2 } });
assert.equal(extractJSON("no json here"), null);

// 2. Provider figures are never overwritten; analyst exposure kept
const prov = { exposure: 12, source: "MSCI ESG Research", basis: "MSCI" };
const m1 = mergeScore(prov, { exposure_pct: 1, likelihood: 70, controversy: { level: "low", items: [] } }, { web: false, what: ["revenue", "controversies"], urls: new Map() });
assert.equal(m1.exposure, 12);
assert.equal(m1.source, "MSCI ESG Research");
assert.equal(m1.likelihood, 70);

// 3. Web results: URLs not seen in search results are dropped, and an unsourced claim becomes "none"
const urls = new Map([["https://news.example/a", "Real article"]]);
const m2 = mergeScore(null, { exposure_pct: 2, likelihood: 60, controversy: { level: "high", summary: "x", items: [{ title: "Real", url: "https://news.example/a", date: "2026-05-01" }, { title: "Made up", url: "https://fake.example/b" }] } }, { web: true, what: ["revenue", "controversies"], urls });
assert.equal(m2.controversy.sources.length, 1);
assert.equal(m2.controversy.level, "high");
const m3 = mergeScore(null, { controversy: { level: "severe", items: [{ title: "x", url: "https://fake.example/c" }] } }, { web: true, what: ["controversies"], urls });
assert.equal(m3.controversy.level, "none");

// 4. Full screenHolding with a fake Claude client that pauses once and returns web results
let calls = 0;
const fake = {
  messages: {
    async create(req) {
      calls++;
      if (calls === 1) {
        assert.ok(req.tools && req.tools[0].type === "web_search_20250305");
        return { stop_reason: "pause_turn", content: [{ type: "server_tool_use", id: "s1", name: "web_search", input: { query: "Meta military" } }, { type: "web_search_tool_result", tool_use_id: "s1", content: [{ type: "web_search_result", url: "https://news.example/meta", title: "Meta and Anduril win Army headset contract" }] }] };
      }
      return { stop_reason: "end_turn", content: [{ type: "text", text: JSON.stringify({ company: "Meta", summary: "s", criteria: [{ id: "c1", exposure_pct: 0.2, likelihood: 70, confidence: "medium", rationale: "r", signals: [], controversy: { level: "high", summary: "Army XR headset partnership with Anduril.", last: "2025-09-01", items: [{ title: "Meta and Anduril win Army headset contract", date: "2025-09-01", url: "https://news.example/meta" }] } }] }) }] };
    },
  },
};
const out = await screenHolding(fake, { model: "test", holding: { id: "h1", name: "Meta Platforms", ticker: "META", scores: {} }, criteria: [{ id: "c1", label: "Military", threshold: 0 }], what: ["revenue", "controversies"], web: true, existingUrls: new Set() });
assert.equal(calls, 2);
assert.equal(out.scores.c1.controversy.level, "high");
assert.equal(out.scores.c1.source, "AI web agent");
assert.equal(out.alerts.length, 1);
assert.equal(out.alerts[0].severity, "high");
assert.deepEqual(out.alerts[0].tickers, ["META"]);

// 5. Prompt mentions the company and the criterion id
const p = buildScreenPrompt({ company: { name: "Meta Platforms" }, criteria: [{ id: "c1", label: "Military" }], what: ["controversies"], web: true });
assert.ok(p.includes("Meta Platforms") && p.includes('id "c1"'));

console.log("All screening self-tests passed.");
