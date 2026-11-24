/* Contrast regression for opt-in large display gradients and solid fallbacks.
 * WCAG 2.2 SC 1.4.3: >=3:1 large text; >=4.5:1 ordinary solid text.
 * Browser QA separately checks rendered type size, placement and fallback CSS. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const css = fs.readFileSync(path.join(__dirname, "../assets/privatefind-theme.css"), "utf8");
function token(name) {
    const value = css.match(new RegExp("--" + name + ":\\s*(#[a-fA-F0-9]{6})\\s*;"))?.[1];
    assert(value, "Missing color token " + name);
    return [1, 3, 5].map(offset => parseInt(value.slice(offset, offset + 2), 16) / 255);
}
function luminance(rgb) {
    return rgb.reduce((total, c, index) => total + [0.2126, 0.7152, 0.0722][index] *
        (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4), 0);
}
function contrast(a, b) {
    const [lo, hi] = [luminance(a), luminance(b)].sort((x, y) => x - y);
    return (hi + 0.05) / (lo + 0.05);
}
const stops = [token("brand-purple"), token("brand-blue"), token("brand-text-cyan")];
const backgrounds = {paper: token("paper"), sidebar: token("sidebar-bg"), white: [1, 1, 1]};
for (const [name, bg] of Object.entries(backgrounds)) {
    let minimum = Infinity;
    for (let segment = 0; segment < 2; segment++) {
        for (let i = 0; i <= 1000; i++) {
            const t = i / 1000;
            const sample = stops[segment].map((c, channel) => c * (1 - t) + stops[segment + 1][channel] * t);
            minimum = Math.min(minimum, contrast(sample, bg));
        }
    }
    assert(minimum >= 3, `Display gradient on ${name} drops to ${minimum}:1`);
    const fallback = contrast(token("brand-solid"), bg);
    assert(fallback >= 4.5, `Solid fallback on ${name} drops to ${fallback}:1`);
    console.log(`PASS: ${name}: gradient minimum ${minimum.toFixed(2)}:1; solid fallback ${fallback.toFixed(2)}:1`);
}
for (const name of ["ink", "muted", "danger", "warning", "success"]) {
    const ratio = contrast(token(name), backgrounds.paper);
    assert(ratio >= 4.5, `${name} on warm white drops to ${ratio}:1`);
}
console.log("PASS: solid body, secondary, warning, error and success text retain normal-text contrast on warm white");
