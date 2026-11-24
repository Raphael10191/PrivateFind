/* Behavior checks for the audit fixes. Node 18+, Python + existing Jinja dependency. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {spawnSync} = require("node:child_process");
const root = path.resolve(__dirname, "../..");
const shared = fs.readFileSync(path.join(root, "frontend/assets/privatefind.js"), "utf8");
const ui = fs.readFileSync(path.join(root, "frontend/assets/privatefind-ui.js"), "utf8");
const helperScope = {window: {}};
vm.runInNewContext(shared.slice(0, shared.indexOf("const menu =")), helperScope);
const api = helperScope.window.privateFind;
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const target = extra => ({events: {}, hidden: false, textContent: "", ...extra,
    addEventListener(name, callback) { this.events[name] = callback; }});

function reportsFixture(href) {
    const location = new URL(href), events = {}, history = [];
    const cards = [
        {dataset: {status: "active"}, textContent: "Black Headphones Library Searching"},
        {dataset: {status: "active"}, textContent: "Brown Wallet Cafeteria Searching"},
        {dataset: {status: "completed"}, textContent: "Water Bottle Lecture Hall Resolved"},
    ];
    const buttons = ["all", "active", "completed"].map(filter => {
        const states = new Set();
        return target({dataset: {filter}, classList: {toggle(name, value) {
            if (value) states.add(name); else states.delete(name);
        }}, attributes: {}, setAttribute(name, value) { this.attributes[name] = value; }});
    });
    const form = target(), input = target({value: "", closest: () => form,
        getClientRects: () => [{}], focus() { this.focused = true; }});
    const feedback = target(), empty = target(), actions = target(), help = target(), clear = target();
    const ids = {"workspace-query": input, "reports-list": {querySelectorAll: () => cards},
        "report-search-feedback": feedback, "filter-empty": empty, "report-filter-actions": actions,
        "report-filter-help": help, "clear-report-filters": clear};
    vm.runInNewContext(ui, {window: {location, history: {pushState(_, __, url) {
        history.push(location.href); location.href = url;
    }}, addEventListener(name, callback) { events[name] = callback; }},
        document: {querySelector: () => null, getElementById: id => ids[id] || null,
            querySelectorAll: () => buttons}, URL, URLSearchParams});
    return {cards, buttons, input, form, feedback, empty, actions, help, clear, location, history, events,
        visible: () => cards.filter(card => !card.hidden)};
}

async function runTests() {
    const checks = [];
    const reports = reportsFixture("http://localhost/owner/reports?q=wallet&status=completed");
    assert.equal(reports.visible().length, 0);
    assert.match(reports.empty.textContent, /No completed reports match “wallet”/);
    assert.equal(reports.actions.hidden, false);
    assert.equal(reports.help.hidden, false);
    checks.push("zero results explain both the query and status constraint and expose a reset");
    reports.buttons[1].events.click();
    assert.equal(reports.visible().length, 1);
    assert.match(reports.visible()[0].textContent, /Wallet/);
    assert.equal(reports.location.searchParams.get("q"), "wallet");
    assert.equal(reports.location.searchParams.get("status"), "active");
    reports.input.value = "bottle";
    reports.form.events.submit({preventDefault() {}});
    assert.equal(reports.visible().length, 0);
    assert.equal(reports.location.searchParams.get("status"), "active");
    checks.push("search preserves the selected status and shares the current query/filter in the URL");
    const previous = reports.location.href;
    reports.clear.events.click();
    assert.equal(reports.visible().length, 3);
    assert.equal(reports.input.value, "");
    assert.equal(reports.location.search, "");
    assert.equal(reports.actions.hidden, true);
    assert(reports.input.focused);
    reports.location.href = previous;
    reports.events.popstate();
    assert.equal(reports.visible().length, 0);
    assert.equal(reports.input.value, "bottle");
    assert.equal(reports.buttons[1].attributes["aria-pressed"], "true");
    checks.push("clear restores all reports and browser Back restores the prior search and active filter");

    const cases = [
        {category: "bottle", model: "Water Bottle", color: "black"},
        {category: "headphones", color: "black"},
        {category: "phone", brand: "Apple", model: "iPhone X"},
        {category: "headphones", brand: "Sony"},
        {category: "other", description: "   "},
        {category: "other", description: "An unusual item ".repeat(10)},
    ];
    const rendered = spawnSync("python", ["-c", [
        "import sys,json", "sys.path.insert(0,'frontend')", "from preview import templates",
        "macro=templates.get_template('report_ui.html').module.report_title",
        "print(json.dumps([macro(row) for row in json.load(sys.stdin)]))",
    ].join(";")], {cwd: root, input: JSON.stringify(cases), encoding: "utf8"});
    assert.equal(rendered.status, 0, rendered.stderr);
    assert.deepEqual(JSON.parse(rendered.stdout), cases.map(report => api.reportTitle(report)));
    assert.equal(api.reportTitle(cases[0]), "Water Bottle");
    checks.push("dashboard, report list, details and ownership context use matching item names across both renderers");

    async function contextFixture(search, fail = false) {
        const name = target(), summary = target(), requests = [];
        const ids = {"ownership-context": {}, "ownership-report-name": name, "ownership-item-summary": summary};
        const contextualAPI = {...api, async requestJSON(url) {
            requests.push(url);
            if (fail === "malformed") return null;
            if (fail) throw new Error("Offline");
            return url.endsWith("/candidates?refresh=false")
                ? [{found_item_id: 10, category: "headphones", color: "black", location: "library",
                    found_date: "2026-11-18", private_attributes: "DO NOT SHOW", photo: "DO NOT SHOW"}]
                : {id: 1, category: "headphones", color: "black"};
        }};
        vm.runInNewContext(ui, {window: {location: {search}, privateFind: contextualAPI},
            document: {querySelector: () => null, getElementById: id => ids[id] || null},
            URLSearchParams, Intl});
        await flush();
        return {name, summary, requests};
    }
    const context = await contextFixture("?report_id=1&item_id=10");
    assert.match(context.name.textContent, /Black Headphones/);
    assert.match(context.summary.textContent, /Black Headphones · Library · Nov 18, 2026/);
    assert(!context.summary.textContent.includes("DO NOT SHOW"));
    assert.deepEqual(context.requests, ["/api/lost-reports/1", "/api/lost-reports/1/candidates?refresh=false"]);
    checks.push("ownership summary reads only the existing owner/public candidate endpoints and never renders private fields");
    const offline = await contextFixture("?report_id=1&item_id=10", true);
    assert.match(offline.summary.textContent, /Public details are currently unavailable/);
    const malformed = await contextFixture("?report_id=1&item_id=10", "malformed");
    assert.match(malformed.name.textContent, /details are currently unavailable/);
    assert.match(malformed.summary.textContent, /Public details are currently unavailable/);
    const invalid = await contextFixture("?report_id=bad&item_id=10");
    assert.equal(invalid.requests.length, 0);
    assert.match(invalid.name.textContent, /valid lost report/);
    checks.push("missing context and invalid links provide honest fallback guidance without inventing a match");
    return {passed: checks.length, checks};
}
runTests().then(result => console.log(JSON.stringify(result, null, 2))).catch(error => {
    console.error(error); process.exitCode = 1;
});
