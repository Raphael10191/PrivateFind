/* Frontend presentation. Mutating API requests stay in the existing workflow scripts. */
(() => {
    const profile = document.querySelector("[data-profile-menu]");
    if (profile) {
        document.addEventListener("click", event => {
            if (!profile.contains(event.target)) profile.open = false;
        });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && profile.open) {
                profile.open = false;
                profile.querySelector("summary").focus();
            }
        });
    }

    const recheck = document.querySelector("[data-ai-retry]");
    if (recheck) recheck.addEventListener("click", async () => {
        const feedback = document.getElementById("service-recheck-feedback");
        const recovery = document.querySelector("[data-ai-recovery]");
        recheck.disabled = true;
        recheck.textContent = "Checking…";
        feedback.hidden = false;
        feedback.textContent = "Checking the required service…";
        try {
            await window.privateFind.refreshAIStatus();
            feedback.textContent = recovery.hidden
                ? "Availability checked. Available actions are ready below."
                : "The required service is still unavailable. This check did not submit your form.";
        } catch {
            feedback.textContent = "We couldn’t check availability. Please check your connection and try again.";
        } finally {
            recheck.disabled = false;
            recheck.textContent = "Check availability";
        }
    });

    // Only the owner's existing report endpoint and public candidate fields are
    // used for context. No private found-item/photo endpoint or new write is used.
    const ownershipContext = document.getElementById("ownership-context");
    if (ownershipContext) void loadOwnershipContext();
    async function loadOwnershipContext() {
        const params = new URLSearchParams(window.location.search);
        const reportId = params.get("report_id");
        const itemId = params.get("item_id");
        const reportName = document.getElementById("ownership-report-name");
        const summary = document.getElementById("ownership-item-summary");
        if (!/^[1-9]\d*$/.test(reportId || "") || !/^[1-9]\d*$/.test(itemId || "")) {
            reportName.textContent = "Choose an item from a valid lost report.";
            summary.textContent = "Return to My Reports to review your possible matches.";
            return;
        }
        const base = "/api/lost-reports/" + encodeURIComponent(reportId);
        const [report, candidates] = await Promise.allSettled([
            window.privateFind.requestJSON(base),
            window.privateFind.requestJSON(base + "/candidates?refresh=false"),
        ]);
        reportName.textContent = report.status === "fulfilled" && report.value && String(report.value.id) === reportId
            ? "Your report: " + window.privateFind.reportTitle(report.value)
            : "Your lost report #" + reportId + " · details are currently unavailable.";
        const candidate = candidates.status === "fulfilled" && Array.isArray(candidates.value)
            ? candidates.value.find(item => String(item.found_item_id) === itemId) : null;
        if (!candidate) {
            summary.textContent = "Selected found item #" + itemId + ". Public details are currently unavailable; return to your report to review the match.";
            return;
        }
        const name = [candidate.color, candidate.category].filter(Boolean)
            .map(value => window.privateFind.humanize(value)).join(" ");
        const place = window.privateFind.humanize(candidate.location || "Location not specified");
        const date = /^\d{4}-\d{2}-\d{2}$/.test(candidate.found_date || "")
            ? new Date(candidate.found_date + "T00:00:00Z") : null;
        const dateLabel = date && !Number.isNaN(date.getTime())
            ? new Intl.DateTimeFormat("en", {dateStyle: "medium", timeZone: "UTC"}).format(date) : "Date not specified";
        summary.textContent = "Selected item: " + (name || "Found item") + " · " + place + " · " + dateLabel;
    }

    const inputs = [document.getElementById("workspace-query"), document.getElementById("reports-query")].filter(Boolean);
    const reportList = document.getElementById("reports-list");
    if (!reportList) return;
    const cards = [...reportList.querySelectorAll(".report-card")];
    const buttons = [...document.querySelectorAll(".filter-button")];
    const feedback = document.getElementById("report-search-feedback");
    const empty = document.getElementById("filter-empty");
    const actions = document.getElementById("report-filter-actions");
    const help = document.getElementById("report-filter-help");
    let query = "";
    let filter = "all";

    function renderReports() {
        let count = 0;
        for (const card of cards) {
            card.hidden = !((filter === "all" || card.dataset.status === filter) &&
                card.textContent.toLowerCase().includes(query.toLowerCase()));
            if (!card.hidden) count++;
        }
        for (const button of buttons) {
            const active = button.dataset.filter === filter;
            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));
        }
        for (const input of inputs) input.value = query;
        const statusLabel = filter === "all" ? "" : filter + " ";
        if (feedback) {
            feedback.hidden = !query && filter === "all";
            feedback.textContent = `${count} ${statusLabel}${count === 1 ? "report" : "reports"}` + (query ? ` matching “${query}”` : "");
        }
        if (empty && cards.length) {
            empty.hidden = count !== 0;
            empty.textContent = `No ${statusLabel}reports` + (query ? ` match “${query}”.` : " in this category.") + " Clear search and filters to see all your reports.";
        }
        if (actions) actions.hidden = !query && filter === "all";
        if (help) help.hidden = filter !== "completed";
    }
    function updateURL() {
        const url = new URL(window.location.href);
        if (query) url.searchParams.set("q", query); else url.searchParams.delete("q");
        if (filter !== "all") url.searchParams.set("status", filter); else url.searchParams.delete("status");
        if (url.href !== window.location.href) window.history.pushState(null, "", url.href);
    }
    function restoreFromURL() {
        const params = new URLSearchParams(window.location.search);
        query = (params.get("q") || "").trim();
        filter = ["active", "completed"].includes(params.get("status")) ? params.get("status") : "all";
        renderReports();
    }
    for (const button of buttons) button.addEventListener("click", () => {
        filter = button.dataset.filter;
        renderReports();
        updateURL();
    });
    for (const input of inputs) input.closest("form").addEventListener("submit", event => {
        event.preventDefault();
        query = input.value.trim();
        renderReports();
        updateURL();
    });
    document.getElementById("clear-report-filters")?.addEventListener("click", () => {
        query = "";
        filter = "all";
        renderReports();
        updateURL();
        const visibleInput = inputs.find(input => input.getClientRects().length > 0);
        visibleInput?.focus();
    });
    window.addEventListener("popstate", restoreFromURL);
    restoreFromURL();
})();

/* Peek interaction adapted from the supplied Peek Blob by Louis Studios.
 * Keeps the original cat and blends a localized closed-eye frame for blinks.
 * No canvas, dependencies, or API calls are needed. */
(() => {
    const scene = document.querySelector("[data-peek-cat]");
    if (!scene) return;
    const cat = scene.querySelector(".sidebar-cat");
    const blink = scene.querySelector(".sidebar-cat-blink");
    const play = scene.querySelector("[data-cat-play]");
    const pause = scene.querySelector("[data-cat-pause]");
    const hint = scene.querySelector("#sidebar-cat-hint");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let paused = false, visible = false, suspended = false, frame = null, previous = null;
    let elapsed = 0, duckAt = -Infinity, pointerAt = -Infinity, pointerX = 0, pointerY = 0;
    let x = 0, y = 0, vx = 0, vy = 0;
    let blinkAt = -Infinity, nextBlink = 3.2, doubleBlink = false;
    let bounds = scene.getBoundingClientRect();
    const clamp = value => Math.max(-1, Math.min(1, value));
    const active = () => visible && !paused && !reduced.matches && !document.hidden && !suspended;

    function duckShape(t) {
        if (t < 0 || t > 2.7) return 0;
        if (t < 0.13) return 1 - (1 - t / 0.13) ** 3;
        if (t < 0.2) return 1;
        return Math.exp(-5.2 * (t - 0.2)) * Math.cos(8.4 * (t - 0.2));
    }
    function updateControls() {
        play.disabled = reduced.matches || paused;
        pause.disabled = reduced.matches;
        pause.textContent = reduced.matches ? "Reduced motion on" : paused ? "Resume animation" : "Pause animation";
        hint.textContent = reduced.matches ? "Your little search companion." : paused ? "Your cat is taking a break." : "Tap the cat for a little peek.";
    }
    function stop() {
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        previous = null;
        duckAt = -Infinity;
        pointerAt = -Infinity;
        x = y = vx = vy = 0;
        cat.style.transform = "";
        blink.style.opacity = "0";
        blinkAt = -Infinity;
        nextBlink = elapsed + 3.2;
        doubleBlink = false;
    }
    function sync() {
        updateControls();
        if (!active()) stop();
        else if (frame === null) frame = requestAnimationFrame(tick);
    }
    function tick(now) {
        frame = null;
        if (!active()) { stop(); return; }
        const dt = previous === null ? 0 : Math.min((now - previous) / 1000, 0.05);
        previous = now;
        elapsed += dt;
        if (elapsed >= nextBlink) {
            blinkAt = elapsed;
            // Occasional double blinks; never queue a chain of repeated ones.
            const followUp = !doubleBlink && Math.random() < 0.15;
            nextBlink = elapsed + (followUp ? 0.48 : 3 + Math.random() * 3.5);
            doubleBlink = followUp;
        }
        const age = elapsed - blinkAt;
        const smooth = value => value * value * (3 - 2 * value);
        const closed = age < 0.075 ? smooth(age / 0.075) : age < 0.12 ? 1
            : age < 0.24 ? 1 - smooth((age - 0.12) / 0.12) : 0;
        // A missing/loading blink asset leaves the original eye visible.
        blink.style.opacity = blink.complete && blink.naturalWidth ? closed.toFixed(3) : "0";
        const following = elapsed - pointerAt < 2.6;
        const tx = following ? pointerX : Math.sin(elapsed * Math.PI / 5) * 0.32;
        const ty = following ? pointerY : Math.sin(elapsed * Math.PI / 3.7) * 0.16;
        const steps = Math.max(1, Math.ceil(dt * 240)), step = dt / steps;
        for (let i = 0; i < steps; i++) {
            vx += (196 * (tx - x) - 16.52 * vx) * step;
            vy += (196 * (ty - y) - 16.52 * vy) * step;
            x += vx * step;
            y += vy * step;
        }
        const duck = duckShape(elapsed - duckAt);
        const breath = Math.sin(elapsed * Math.PI * 2 / 5);
        cat.style.transform = `translate3d(${(x * 4).toFixed(2)}px, ${(duck * 103 + y * 1.5).toFixed(2)}%, 0) rotate(${(x * 3).toFixed(2)}deg) scale(${(1 + breath * 0.006).toFixed(4)}, ${(1 + breath * 0.009).toFixed(4)})`;
        frame = requestAnimationFrame(tick);
    }
    function refreshBounds() { bounds = scene.getBoundingClientRect(); }
    function trackPointer(event) {
        if (!active() || event.pointerType === "touch") return;
        pointerX = clamp((event.clientX - bounds.left - bounds.width / 2) / Math.max(160, window.innerWidth / 2));
        pointerY = clamp((event.clientY - bounds.top - bounds.height / 2) / Math.max(160, window.innerHeight / 2));
        pointerAt = elapsed;
    }
    // A native button supplies click, touch, Enter and Space activation once.
    play.addEventListener("click", () => {
        if (!active() || elapsed - duckAt < 0.8) return;
        duckAt = elapsed;
    });
    pause.addEventListener("click", () => { paused = !paused; sync(); });
    const observer = new IntersectionObserver(entries => {
        visible = entries.some(entry => entry.isIntersecting);
        refreshBounds();
        sync();
    });
    observer.observe(scene);
    pause.hidden = false;
    window.addEventListener("pointermove", trackPointer, {passive: true});
    window.addEventListener("resize", refreshBounds, {passive: true});
    window.addEventListener("scroll", refreshBounds, {passive: true});
    document.addEventListener("visibilitychange", sync);
    reduced.addEventListener("change", sync);
    // Stop on navigation, and restore correctly after back/forward cache reuse.
    window.addEventListener("pagehide", () => { suspended = true; stop(); });
    window.addEventListener("pageshow", () => { suspended = false; refreshBounds(); sync(); });
    sync();
})();
