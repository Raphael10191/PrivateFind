/* Behavior checks for the image-based sidebar interaction; no browser or API. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../assets/privatefind-ui.js"), "utf8");
const script = source.slice(source.indexOf("/* Peek interaction"));
function fixture(reduce = false) {
    const windowEvents = {}, documentEvents = {}, frames = new Map();
    let nextFrame = 0, now = 0, intersection, preferenceChange;
    const target = extra => ({events: {}, ...extra,
        addEventListener(name, callback) { this.events[name] = callback; }});
    const cat = {style: {}}, blink = {style: {}, complete: true, naturalWidth: 1254}, hint = {}, play = target(), pause = target({hidden: true});
    const scene = {querySelector: selector => ({".sidebar-cat": cat, "[data-cat-play]": play,
        "[data-cat-pause]": pause, "#sidebar-cat-hint": hint, ".sidebar-cat-blink": blink})[selector],
        getBoundingClientRect: () => ({left: 20, top: 400, width: 180, height: 235})};
    const media = {matches: reduce, addEventListener(_, callback) { preferenceChange = callback; }};
    const document = {hidden: false, querySelector: () => scene,
        addEventListener(name, callback) { documentEvents[name] = callback; }};
    vm.runInNewContext(script, {document, window: {innerWidth: 1246, innerHeight: 678,
        matchMedia: () => media, addEventListener(name, callback) { windowEvents[name] = callback; }},
        IntersectionObserver: class { constructor(callback) { intersection = callback; } observe() {} },
        requestAnimationFrame(callback) { frames.set(++nextFrame, callback); return nextFrame; },
        cancelAnimationFrame(id) { frames.delete(id); },
        fetch() { throw new Error("The mascot must never request an API."); }});
    return {cat, blink, hint, play, pause, frames, windowEvents,
        show(value) { intersection([{isIntersecting: value}]); },
        visibility(hidden) { document.hidden = hidden; documentEvents.visibilitychange(); },
        reduce(value) { media.matches = value; preferenceChange(); },
        step(ms = 16) { now += ms; const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback(now)); },
        click(button) { if (!button.disabled) button.events.click(); },
        offset() { return Number(cat.style.transform.match(/, ([-\d.]+)%/)[1]); }};
}
const f = fixture();
assert.equal(f.frames.size, 0);
f.show(true); f.step(); f.step();
assert.equal(f.frames.size, 1);
assert.match(f.cat.style.transform, /translate3d/);
console.log("PASS: animation starts only when the mascot is visible");
f.windowEvents.pointermove({clientX: 1246, clientY: 0, pointerType: "mouse"});
for (let i = 0; i < 90; i++) f.step();
assert(Number(f.cat.style.transform.match(/rotate\(([-\d.]+)/)[1]) > 1);
f.windowEvents.pointermove({clientX: -10000, clientY: 10000, pointerType: "touch"});
f.step();
assert(Number(f.cat.style.transform.match(/rotate\(([-\d.]+)/)[1]) > 1);
console.log("PASS: bounded pointer response ignores touch scrolling");
f.click(f.play);
for (let i = 0; i < 9; i++) f.step();
assert(f.offset() > 90);
f.click(f.play); // Rapid repeated activation must not trap it below the ledge.
for (let i = 0; i < 180; i++) f.step();
assert(Math.abs(f.offset()) < 2);
assert(!/NaN|Infinity/.test(f.cat.style.transform));
console.log("PASS: click ducks and springs back, including rapid repeated clicks");
f.click(f.pause);
assert.equal(f.frames.size, 0);
assert.equal(f.cat.style.transform, "");
assert(f.play.disabled);
assert.equal(f.pause.textContent, "Resume animation");
f.click(f.pause);
assert.equal(f.frames.size, 1);
f.show(false); assert.equal(f.frames.size, 0);
f.show(true); f.visibility(true); assert.equal(f.frames.size, 0);
f.visibility(false); assert.equal(f.frames.size, 1);
console.log("PASS: pause, offscreen and hidden tabs stop work; resume restarts one loop");
f.windowEvents.pagehide(); assert.equal(f.frames.size, 0);
f.windowEvents.pageshow(); f.windowEvents.pageshow(); assert.equal(f.frames.size, 1);
f.step(60000);
assert(!/NaN|Infinity/.test(f.cat.style.transform));
console.log("PASS: back/forward cache and long frame gaps recover safely");
f.reduce(true);
assert.equal(f.frames.size, 0); assert.equal(f.cat.style.transform, "");
assert(f.play.disabled); assert(f.pause.disabled);
f.reduce(false); assert.equal(f.frames.size, 1);
const still = fixture(true); still.show(true); still.click(still.play);
assert.equal(still.frames.size, 0);
console.log("PASS: system reduced motion is respected on load and when changed live");

const blinking = fixture(); blinking.show(true); blinking.step();
let closedFrames = 0, openFrames = 0;
for (let i = 0; i < 480; i++) {
    blinking.step();
    const opacity = Number(blinking.blink.style.opacity);
    assert(opacity >= 0 && opacity <= 1);
    if (opacity > 0.95) closedFrames++;
    if (opacity === 0) openFrames++;
}
assert(closedFrames >= 2 && closedFrames < 30);
assert(openFrames > 400);
blinking.click(blinking.pause);
assert.equal(blinking.blink.style.opacity, "0");
blinking.reduce(true);
assert.equal(blinking.blink.style.opacity, "0");
const missing = fixture(); missing.blink.naturalWidth = 0; missing.show(true);
for (let i = 0; i < 250; i++) missing.step();
assert.equal(missing.blink.style.opacity, "0");
console.log("PASS: brief blinks reopen, pause/reduced motion restore open eyes, and missing artwork fails safely");
