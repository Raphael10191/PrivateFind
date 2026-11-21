/* Node 18+, no packages: node frontend/tests/companion_motion.test.cjs */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../assets/privatefind.js"), "utf8");
const companions = source.slice(source.indexOf("const companionScenes ="));

function fixture({reduced = false, fine = true, observe = true} = {}) {
    const node = () => ({dataset: {}, events: {}, styles: new Map(),
        addEventListener(name, callback) { this.events[name] = callback; },
        style: null,
    });
    const lookout = node(), chirp = node(), sidebar = node(), empty = node();
    for (const element of [lookout, chirp, sidebar, empty]) {
        element.style = {
            setProperty: (name, value) => element.styles.set(name, value),
            removeProperty: name => element.styles.delete(name),
        };
    }
    chirp.getBoundingClientRect = () => ({left: 0, top: 0, width: 200, height: 200});
    lookout.querySelector = () => chirp;
    const media = matches => ({matches, addEventListener(_, callback) { this.change = callback; }});
    const motion = media(reduced), pointer = media(fine), documentEvents = {}, frames = new Map();
    let nextFrame = 1, intersection;
    const document = {hidden: false, querySelectorAll: () => [sidebar, empty, chirp],
        querySelector: () => lookout, addEventListener: (name, callback) => { documentEvents[name] = callback; }};
    const window = {matchMedia: query => query.includes("reduced-motion") ? motion : pointer};
    const Observer = class {
        constructor(callback) { intersection = callback; }
        observe() {}
    };
    if (observe) window.IntersectionObserver = Observer;
    vm.runInNewContext(companions, {window, document, IntersectionObserver: Observer,
        requestAnimationFrame: callback => { const id = nextFrame++; frames.set(id, callback); return id; },
        cancelAnimationFrame: id => frames.delete(id),
    });
    return {lookout, chirp, sidebar, empty, document, motion, pointer, frames,
        visible(target, ratio = 1) { intersection([{target, isIntersecting: ratio > 0, intersectionRatio: ratio}]); },
        hide(value) { document.hidden = value; documentEvents.visibilitychange(); },
        move(x, y, pointerType = "mouse") { lookout.events.pointermove({clientX: x, clientY: y, pointerType}); },
        flush() { for (const [id, callback] of [...frames]) { frames.delete(id); callback(); } },
    };
}

function runTests() {
    const checks = [];
    const view = fixture();
    assert.equal(view.sidebar.dataset.mascotActive, "false");
    view.visible(view.sidebar);
    assert.equal(view.sidebar.dataset.mascotActive, "true");
    assert.equal(view.empty.dataset.mascotActive, "false");
    checks.push("each decoration becomes active only when it is sufficiently visible");

    view.visible(view.chirp);
    view.move(10000, -10000); view.move(10000, -10000);
    assert.equal(view.frames.size, 1);
    view.flush();
    assert.equal(view.lookout.styles.get("--chirp-x"), "3.00px");
    assert.equal(view.lookout.styles.get("--chirp-y"), "-2.00px");
    assert.equal(view.lookout.styles.get("--chirp-turn"), "3.00deg");
    assert.equal(view.frames.size, 0);
    checks.push("pointer reactions are small, bounded, and scheduled once per input frame");

    const privateField = id => Object.defineProperty({id}, "value", {
        get() { throw new Error("Animation must never read an input value"); },
    });
    view.lookout.events.focusin({target: privateField("email")});
    assert.equal(view.lookout.dataset.chirpFocus, "email");
    view.lookout.events.focusin({target: privateField("password")});
    assert.equal(view.lookout.dataset.chirpFocus, "password");
    view.move(200, 200);
    assert.equal(view.frames.size, 0);
    assert.equal(view.lookout.styles.size, 0);
    for (const name of ["input", "change", "keydown", "keyup", "submit"]) {
        assert.equal(view.lookout.events[name], undefined);
    }
    checks.push("focus reactions never read values or observe typing, input changes, or submission");

    view.lookout.events.focusout();
    assert.equal(view.lookout.dataset.chirpFocus, "");
    view.move(200, 200);
    view.lookout.events.pointerleave();
    assert.equal(view.frames.size, 0);
    assert.equal(view.lookout.styles.size, 0);
    checks.push("blur and pointer leave clear pending motion and restore neutral orientation");

    view.move(200, 200);
    view.visible(view.chirp, 0);
    assert.equal(view.frames.size, 0);
    view.hide(true);
    assert.equal(view.sidebar.dataset.mascotActive, "false");
    view.hide(false);
    assert.equal(view.sidebar.dataset.mascotActive, "true");
    checks.push("offscreen and hidden-tab work pauses and resumes independently");

    view.visible(view.chirp);
    view.motion.matches = true; view.motion.change();
    view.move(200, 200);
    assert.equal(view.frames.size, 0);
    assert.equal(view.chirp.dataset.mascotActive, "false");
    const touch = fixture({fine: false}); touch.visible(touch.chirp);
    touch.move(200, 200); touch.move(200, 200, "touch");
    assert.equal(touch.frames.size, 0);
    checks.push("reduced motion and touch-only devices disable pointer tracking");

    const fallback = fixture({observe: false});
    assert.equal(fallback.chirp.dataset.mascotActive, "false");
    assert(!/fetch\(|setInterval\(|setTimeout\(|\.value\b|localStorage|sessionStorage/.test(companions));
    checks.push("static fallback adds no requests, timers, storage, or access to field values");
    return {passed: checks.length, checks};
}

module.exports = {runTests};
if (require.main === module) console.log(JSON.stringify(runTests(), null, 2));
