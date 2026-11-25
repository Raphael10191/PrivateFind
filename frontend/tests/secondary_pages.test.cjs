/* Regression checks for async Refresh focus and owner help routing. No backend connection. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const root = path.resolve(__dirname, '../..');
const template = fs.readFileSync(path.join(root, 'frontend/templates/owner_claims.html'), 'utf8');
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

async function run() {
    const doc = {body: {tagName: 'BODY'}};
    doc.activeElement = doc.body;
    const requests = [], pending = [], checks = [];
    function element(tagName = 'DIV') {
        return {tagName, hidden: false, children: [], events: {}, _disabled: false,
            classList: {toggle() {}}, setAttribute() {},
            append(...children) { this.children.push(...children); },
            replaceChildren(...children) { this.children = children; },
            addEventListener(name, callback) { this.events[name] = callback; },
            focus(options) { doc.activeElement = this; this.focusOptions = options; },
            get disabled() { return this._disabled; },
            set disabled(value) {
                this._disabled = value;
                if (value && doc.activeElement === this) doc.activeElement = doc.body;
            }};
    }
    const refresh = element('BUTTON'), list = element(), feedback = element(), art = element();
    const ids = {'refresh-claims': refresh, 'claims-list': list, 'claims-feedback': feedback, 'claims-empty-art': art};
    doc.getElementById = id => ids[id];
    doc.createElement = tag => element(tag.toUpperCase());
    const privateFind = {requestJSON(url) {
        requests.push(url);
        return new Promise((resolve, reject) => pending.push({resolve, reject}));
    }};
    vm.runInNewContext(script, {document: doc, window: {privateFind}, encodeURIComponent});
    pending.shift().resolve([]);
    await flush();
    assert.equal(doc.activeElement, doc.body);
    assert.equal(refresh.disabled, false);
    checks.push('initial claim loading does not steal keyboard focus');

    refresh.focus();
    const loaded = refresh.events.click();
    assert.equal(refresh.disabled, true);
    assert.equal(doc.activeElement, doc.body);
    pending.shift().resolve([]);
    await loaded;
    assert.equal(doc.activeElement, refresh);
    assert.equal(refresh.focusOptions.preventScroll, true);
    checks.push('keyboard Refresh restores its focus without scrolling after success');

    const elsewhere = element('A');
    refresh.focus();
    const moved = refresh.events.click();
    elsewhere.focus();
    pending.shift().resolve([]);
    await moved;
    assert.equal(doc.activeElement, elsewhere);
    checks.push('refresh completion does not steal focus after the user moves elsewhere');

    refresh.focus();
    const failed = refresh.events.click();
    pending.shift().reject(new Error('Offline'));
    await failed;
    assert.equal(doc.activeElement, refresh);
    assert.equal(feedback.textContent, 'Offline');
    assert.equal(refresh.disabled, false);
    assert.deepEqual(requests, Array(4).fill('/api/claims'));
    checks.push('failed Refresh restores focus and preserves the existing request/error path');

    const rendered = spawnSync('python', ['-c', [
        "import sys; sys.path.insert(0,'frontend')",
        "from preview import PAGES,templates",
        "assert PAGES['/owner/how-it-works']==('owner_guide.html','guide')",
        "html=templates.get_template('owner_guide.html').render(role='owner',active_page='guide',reports=[],account={'display_name':'Student','email':'student@example.test'})",
        "assert 'Owner navigation' in html and 'Mobile owner navigation' in html",
        "assert 'href=\"/owner/how-it-works\" aria-current=\"page\"' in html",
        "assert all('href=\"'+url+'\"' in html for url in ['/owner/report/new','/owner/reports','/owner/claims','/found/new'])",
    ].join(';')], {cwd: root, encoding: 'utf8'});
    assert.equal(rendered.status, 0, rendered.stderr);
    checks.push('owner help retains owner navigation, current-page state and existing flow destinations');
    return {passed: checks.length, checks};
}
run().then(result => console.log(JSON.stringify(result, null, 2))).catch(error => {
    console.error(error); process.exitCode = 1;
});
