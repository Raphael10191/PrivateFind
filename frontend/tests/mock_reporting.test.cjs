/* Dependency-free checks: node frontend/tests/mock_reporting.test.cjs (Node 18+). */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../assets/privatefind.js"), "utf8");
const flush = async () => { for (let i = 0; i < 16; i++) await Promise.resolve(); };

async function page(state, { readOnly = false, failure = false } = {}) {
    const status = {hidden: true, textContent: "Checking service availability", dataset: {}};
    const controls = readOnly ? [] : ["report", "claim", "finder"].map(scope => ({
        inert: true, dataset: scope === "report" ? {aiScope: "report"} : {},
        closest: () => null,
    }));
    const requests = [], timers = [], events = {};
    let current = state, failed = failure;
    const context = {
        window: {addEventListener() {}},
        document: {
            body: {classList: {contains: () => false}}, hidden: false,
            querySelector: selector => selector === "[data-requires-ai]" ? controls[0] : null,
            querySelectorAll: selector => selector === "[data-requires-ai]" ? controls : [],
            getElementById: () => status,
            addEventListener: (name, callback) => { events[name] = callback; },
        },
        setInterval: callback => timers.push(callback),
        fetch: async url => {
            requests.push(url);
            if (failed) throw new Error("Offline");
            return {ok: true, json: async () => current};
        },
    };
    vm.createContext(context);
    vm.runInContext(source, context);
    await flush();
    return {
        status, controls, requests, events, api: context.window.privateFind,
        async update(next, fail = false) {
            current = next; failed = fail; timers[0](); await flush();
        },
    };
}

async function runTests() {
    const passed = [];
    for (const provider of ["qwen", "claude"]) {
        const view = await page({provider, available: true});
        assert(view.controls.every(control => control.inert === false));
        await view.update({provider, available: false});
        assert(view.controls.every(control => control.inert));
        passed.push(`${provider}: normal readiness and outage gate preserved`);
    }
    for (const state of [
        {provider: "mock", available: false},
        {provider: "mock", available: true},
        {provider: "mock", available: false, mock_reporting_enabled: "true"},
        {provider: "unknown", available: false, mock_reporting_enabled: true},
    ]) {
        const view = await page(state);
        assert(view.controls.every(control => control.inert));
    }
    passed.push("mock requires the explicit boolean server capability");
    const simulation = {provider: "mock", available: false, mock_reporting_enabled: true};
    const view = await page(simulation);
    assert.equal(view.controls[0].inert, false);
    assert(view.controls.slice(1).every(control => control.inert));
    assert.equal(view.status.hidden, false);
    assert.match(view.status.textContent, /Local development.*Simulated matching/);
    passed.push("only the report form is enabled; claims and Finder remain inert");
    await view.update({}, true);
    assert(view.controls.every(control => control.inert));
    assert.equal(view.status.hidden, false);
    assert.match(view.status.textContent, /Simulated matching.*Submissions are paused/);
    await view.update(simulation);
    assert.equal(view.controls[0].inert, false);
    passed.push("network failure blocks submissions and preserves the simulation notice");
    await view.update({provider: "qwen", available: true});
    assert(view.controls.every(control => control.inert));
    assert.match(view.status.textContent, /reload before continuing/);
    passed.push("switching away from mock requires a fresh page before submitting");
    for (const fail of [false, true]) {
        const readOnly = await page(simulation, {readOnly: true});
        if (fail) await readOnly.update({}, true);
        assert.equal(readOnly.status.hidden, false);
        assert.match(readOnly.status.textContent, /Simulated matching/);
    }
    passed.push("simulation remains visible on read-only report/result screens");
    const unavailable = await page({}, {readOnly: true, failure: true});
    await assert.rejects(
        unavailable.api.requestJSON("/api/lost-reports/1/candidates?refresh=false"),
        /Service availability could not be confirmed/
    );
    assert(unavailable.requests.every(url => url === "/api/ai/status"));
    const labelled = await page(simulation, {readOnly: true});
    await labelled.api.requestJSON("/api/lost-reports/1/candidates?refresh=false");
    assert.equal(labelled.status.hidden, false);
    assert.match(labelled.status.textContent, /Simulated matching/);
    passed.push("candidate loading waits for availability so simulated results cannot precede their label");
    assert(view.requests.every(url => url === "/api/ai/status"));
    const form = fs.readFileSync(path.join(__dirname, "../templates/owner_report_form.html"), "utf8");
    assert.match(form, /data-requires-ai data-ai-scope="report" inert/);
    for (const name of ["owner_claim.html", "finder_deposit.html"]) {
        assert(!fs.readFileSync(path.join(__dirname, "../templates/", name), "utf8")
            .includes('data-ai-scope="report"'));
    }
    passed.push("only the existing report form has report scope; no new API requests");
    return {passed: passed.length, checks: passed};
}

module.exports = {runTests};
if (require.main === module) {
    runTests().then(result => console.log(JSON.stringify(result, null, 2))).catch(error => {
        console.error(error); process.exitCode = 1;
    });
}
