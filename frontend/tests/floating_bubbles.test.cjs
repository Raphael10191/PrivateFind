/* Motion lifecycle checks without a browser, dependencies, API or frame loop. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../assets/privatefind-ui.js'), 'utf8');
const script = source.slice(source.indexOf('/* Shared decorative pause'), source.indexOf('/* Peek interaction'));

function fixture({reduce = false, observe = true, enabled = true} = {}) {
    const events = {}, windowEvents = {};
    const layer = {dataset: {}};
    const controls = [0, 1].map(() => ({attrs: {}, hidden: true,
        setAttribute(key, value) { this.attrs[key] = value; },
        addEventListener(key, callback) { this[key] = callback; }}));
    let intersection, changed = 0;
    const media = {matches: reduce, addEventListener(_, callback) { this.change = callback; }};
    const document = {hidden: false, querySelector: () => enabled ? layer : null,
        querySelectorAll: () => controls, addEventListener(key, callback) { events[key] = callback; },
        dispatchEvent(event) { assert.equal(event.type, 'privatefind:motionchange'); changed++; }};
    const window = {matchMedia: () => media, addEventListener(key, callback) { windowEvents[key] = callback; }};
    if (observe) window.IntersectionObserver = class {
        constructor(callback) { intersection = callback; }
        observe(target) { assert.equal(target, layer); }
    };
    vm.runInNewContext(script, {window, document, CustomEvent: class { constructor(type) { this.type = type; } },
        fetch() { throw new Error('Decoration cannot request data'); },
        requestAnimationFrame() { throw new Error('Bubbles cannot use a rendering loop'); },
        setInterval() { throw new Error('Bubbles cannot poll'); }});
    return {layer, controls, media, window, document, events, windowEvents,
        get changed() { return changed; },
        show(value) { intersection([{isIntersecting: value}]); },
        hidden(value) { document.hidden = value; events.visibilitychange(); },
        reduce(value) { media.matches = value; media.change(); }};
}
const checks = [];
const f = fixture();
assert.equal(f.layer.dataset.bubblesActive, 'false');
f.show(true); assert.equal(f.layer.dataset.bubblesActive, 'true');
f.show(false); assert.equal(f.layer.dataset.bubblesActive, 'false');
checks.push('background starts only in view and pauses offscreen without a frame loop');
f.show(true); f.controls[0].click();
assert.equal(f.window.privateFindMotion.paused, true);
assert.equal(f.layer.dataset.bubblesActive, 'false');
assert(f.controls.every(c => c.attrs['aria-pressed'] === 'true' && c.attrs['aria-label'] === 'Resume animation'));
assert.equal(f.changed, 1);
f.controls[1].click();
assert.equal(f.layer.dataset.bubblesActive, 'true');
assert(f.controls.every(c => c.attrs['aria-pressed'] === 'false'));
checks.push('both controls share pause state, accessible labels and the mascot notification');
f.hidden(true); assert.equal(f.layer.dataset.bubblesActive, 'false');
f.hidden(false); assert.equal(f.layer.dataset.bubblesActive, 'true');
f.windowEvents.pagehide(); assert.equal(f.layer.dataset.bubblesActive, 'false');
f.windowEvents.pageshow(); assert.equal(f.layer.dataset.bubblesActive, 'true');
checks.push('hidden tabs and page lifecycle suspend and restore animation safely');
f.controls[0].click(); f.hidden(true); f.hidden(false); f.windowEvents.pageshow();
assert.equal(f.layer.dataset.bubblesActive, 'false');
assert.equal(f.window.privateFindMotion.paused, true);
checks.push('manual pause survives visibility and back-forward lifecycle changes');
const reduced = fixture({reduce: true}); reduced.show(true);
assert.equal(reduced.layer.dataset.bubblesActive, 'false');
assert(reduced.controls.every(c => c.disabled && c.attrs['aria-label'] === 'Reduced motion on'));
reduced.reduce(false); assert.equal(reduced.layer.dataset.bubblesActive, 'true');
reduced.reduce(true); assert.equal(reduced.layer.dataset.bubblesActive, 'false');
checks.push('reduced motion wins at load and when changed live');
const fallback = fixture({observe: false});
assert.equal(fallback.layer.dataset.bubblesActive, 'false');
const excluded = fixture({enabled: false});
assert.equal(excluded.window.privateFindMotion, undefined);
assert.equal(Object.keys(excluded.events).length, 0);
checks.push('unsupported visibility uses a static fallback and excluded pages install no controller');
console.log(JSON.stringify({passed: checks.length, checks}, null, 2));
