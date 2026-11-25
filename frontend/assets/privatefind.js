window.privateFind = {
    claimMascot(status) {
        return {
            pending: "keeper", in_review: "keeper", approved: "chirp",
            collected: "chirp", handed_over: "pip", rejected: "pip-calm",
            revoked: "pip-calm", unavailable: "pip-calm"
        }[status] || null;
    },
    humanize(value) {
        return String(value ?? "Unknown")
            .replaceAll("_", " ")
            .replace(/\b\w/g, letter => letter.toUpperCase());
    },
    reportTitle(report) {
        const brand = String(report.brand || "").trim();
        const model = String(report.model || "").trim();
        const category = report.category || "other";
        const categoryLabel = category === "other" ? "" : this.humanize(category);
        if (brand || model) return [brand, model || categoryLabel].filter(Boolean).join(" ");
        if (categoryLabel) return [report.color ? this.humanize(report.color) : "", categoryLabel].filter(Boolean).join(" ");
        const description = Array.from(String(report.description || "Lost item").trim() || "Lost item");
        return description.length > 70 ? description.slice(0, 69).join("") + "…" : description.join("");
    },
    formatExpiry(value) {
        const text = String(value ?? "");
        const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : text + "Z");
        if (!text || Number.isNaN(date.getTime())) return text || "Not available";
        return new Intl.DateTimeFormat("en", {
            year: "numeric", month: "short", day: "numeric",
            hour: "numeric", minute: "2-digit", timeZoneName: "short"
        }).format(date);
    },
    adminClaimStatus(claim) {
        if (claim.verification_state === "handed_over") return "Handed over";
        if (claim.status === "approved" && claim.item_status === "returned") return "Returned";
        if (claim.status === "approved" && claim.item_status === "expired") return "Pickup cancelled";
        return window.privateFind.humanize(claim.status);
    },
    createText(tag, value, className = "") {
        const element = document.createElement(tag);
        element.textContent = String(value ?? "");
        if (className) element.className = className;
        return element;
    },
    async requestJSON(url, options = {}, messages = {}) {
        if (/^\/api\/lost-reports\/\d+\/candidates(?:\?|$)/.test(url) &&
            window.privateFind.aiStatusCheck && !(await window.privateFind.aiStatusCheck)) {
            throw new Error("Service availability could not be confirmed. Please try again later.");
        }
        const response = await fetch(url, {
            credentials: "same-origin",
            cache: "no-store",
            ...options,
        });
        if (response.status === 401) {
            window.location.replace("/login");
            throw new Error(messages.session || "Please sign in again.");
        }
        if (messages.admin && response.status === 403) {
            throw new Error("Admin access required.");
        }
        if (messages.conflict && response.status === 409) {
            throw new Error(messages.conflict);
        }
        if (response.ok) {
            return messages.admin ? response.json().catch(() => null) : response.json();
        }

        const data = await response.json().catch(() => null);
        if (messages.ai && data?.error?.code === "ai_unavailable") {
            document.dispatchEvent(new Event("privatefind-ai-unavailable"));
        }
        const fallback = messages.failure || "Request failed (HTTP " + response.status + ").";
        if (messages.admin) {
            if (messages.allowErrorString && typeof data?.error === "string") {
                throw new Error(data.error);
            }
            if (typeof data?.error?.message === "string") throw new Error(data.error.message);
            if (typeof data?.detail === "string") throw new Error(data.detail);
            throw new Error(fallback);
        }
        throw new Error(data?.error?.message || fallback);
    },
};

const menu = document.querySelector(".mobile-more");

if (menu) {
    document.addEventListener("click", event => {
        if (!menu.contains(event.target)) menu.open = false;
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && menu.open) {
            menu.open = false;
            menu.querySelector("summary").focus();
        }
    });
}

document.querySelectorAll("[data-signout]").forEach(button => {
    button.addEventListener("click", async () => {
        button.disabled = true;
        try {
            const response = await fetch("/api/auth/logout", {method: "POST"});
            if (!response.ok) throw new Error("Sign out failed");
            sessionStorage.removeItem("privatefind_lost_report_draft");
            location.replace("/login");
        } catch {
            button.disabled = false;
            window.alert("Could not sign out. Try again.");
        }
    });
});

const aiStatus = document.getElementById("ai-status");
if (aiStatus) {
    let statusVersion = 0;
    let simulatedReportingSeen = false;
    let latestState = {available: false};
    let latestError = "";
    const isOperator = document.body.classList.contains("role-admin");
    if (!isOperator && document.querySelector("[data-requires-ai]")) {
        aiStatus.hidden = false;
    }

    function showAIStatus({provider, available, mock_reporting_enabled}, availabilityError = "") {
        latestState = {provider, available, mock_reporting_enabled};
        latestError = availabilityError;
        const ready = available && ["qwen", "claude"].includes(provider);
        const simulatedReporting = provider === "mock" && mock_reporting_enabled === true;
        if (simulatedReporting) simulatedReportingSeen = true;
        const staleSimulation = simulatedReportingSeen && !simulatedReporting;
        const simulationNotice = "Local development · Simulated matching. Test reports use a temporary test database. Ownership verification, deposits, pickup codes and hardware actions are disabled.";
        const name = {qwen: "Qwen", claude: "Claude"}[provider];
        const operatorMessage = ready
            ? name + " online · Real AI"
            : provider === "mock"
                ? "Technical issue: Mock AI is configured. A real AI provider is required."
                : "Technical issue: " + (name || "AI") + " is unavailable. Try again when it is back.";
        const message = simulatedReporting
            ? simulationNotice
            : staleSimulation
                ? simulationNotice + " Test-mode availability changed or could not be confirmed. Submissions are paused; reload before continuing."
            : isOperator
            ? availabilityError || operatorMessage
            : availabilityError
                ? "We can’t check service availability right now. Submission is paused. Please try again later."
                : "This service is temporarily unavailable. Your form is paused. Please try again later.";
        const hasVisibleForm = [...document.querySelectorAll("[data-requires-ai]")]
            .some(control => !control.closest("[hidden]"));
        aiStatus.hidden = !simulatedReportingSeen && !isOperator && (ready || !hasVisibleForm);
        if (aiStatus.textContent !== message) aiStatus.textContent = message;
        aiStatus.dataset.available = String(ready);
        for (const control of document.querySelectorAll("[data-requires-ai]")) {
            control.inert = !((ready && !staleSimulation) ||
                (simulatedReporting && control.dataset.aiScope === "report"));
        }
        const recovery = document.querySelector("[data-ai-recovery]");
        if (recovery) recovery.hidden = ![...document.querySelectorAll("[data-requires-ai]")]
            .some(control => control.inert && !control.closest("[hidden]"));
    }

    async function refreshAIStatus() {
        const version = ++statusVersion;
        let state = {available: false};
        let availabilityError = "Service availability could not be checked.";
        try {
            const response = await fetch("/api/ai/status", {cache: "no-store"});
            if (response.ok) {
                state = await response.json();
                availabilityError = "";
            } else {
                availabilityError = "Service availability could not be checked (HTTP " + response.status + ").";
            }
        } catch {
            // A disconnected browser cannot submit an AI-dependent form.
        }
        if (version === statusVersion) showAIStatus(state, availabilityError);
        return version === statusVersion && !availabilityError &&
            ["mock", "qwen", "claude"].includes(state.provider);
    }

    function checkAIStatus() {
        window.privateFind.aiStatusCheck = refreshAIStatus();
        return window.privateFind.aiStatusCheck;
    }
    window.privateFind.refreshAIStatus = checkAIStatus;

    // Forms can appear after an async claim/locker lookup. Refresh their notice
    // from the last service result without another request or weakening the guard.
    if (typeof window.MutationObserver === "function") {
        const visibility = new window.MutationObserver(() => showAIStatus(latestState, latestError));
        const targets = new Set();
        for (const control of document.querySelectorAll("[data-requires-ai]")) {
            for (let element = control; element && element !== document.body; element = element.parentElement) {
                targets.add(element);
            }
        }
        for (const target of targets) visibility.observe(target, {attributes: true, attributeFilter: ["hidden"]});
    }

    document.addEventListener("privatefind-ai-unavailable", () => {
        statusVersion += 1;
        showAIStatus({available: false});
    });
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) checkAIStatus();
    });
    window.addEventListener("pageshow", event => {
        if (event.persisted) checkAIStatus();
    });
    setInterval(() => {
        if (!document.hidden) checkAIStatus();
    }, 15000);
    checkAIStatus();
}

// Decorative interaction only: no requests, storage, or changes to Owner workflows.
const ownerScout = document.body.classList.contains("owner-home")
    ? document.querySelector("[data-owner-scout]") : null;
if (ownerScout) {
    const hero = ownerScout.closest("[data-scout-hero]");
    const button = ownerScout.querySelector(".scout-button");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const finePointer = window.matchMedia("(any-hover: hover) and (any-pointer: fine)");
    let inView = false;
    let frame = 0;
    let pointer;

    function resetGaze() {
        if (frame) cancelAnimationFrame(frame);
        frame = 0;
        for (const name of ["--scout-look-x", "--scout-look-y", "--scout-glass-turn"]) {
            ownerScout.style.removeProperty(name);
        }
    }

    function syncEffects() {
        const active = inView && !document.hidden && !reducedMotion.matches && window.privateFindMotion?.paused !== true;
        hero.dataset.scoutActive = String(active);
        if (!active || !finePointer.matches) resetGaze();
        if (!active) button.classList.remove("is-peeking");
    }

    function lookAtPointer(event) {
        if (event.pointerType !== "mouse" || !finePointer.matches || hero.dataset.scoutActive !== "true") return;
        pointer = {x: event.clientX, y: event.clientY};
        if (frame) return;
        frame = requestAnimationFrame(() => {
            frame = 0;
            const bounds = button.getBoundingClientRect();
            const clamp = value => Math.max(-1, Math.min(1, value));
            const x = clamp((pointer.x - bounds.left - bounds.width / 2) / (bounds.width / 2));
            const y = clamp((pointer.y - bounds.top - bounds.height / 2) / (bounds.height / 2));
            ownerScout.style.setProperty("--scout-look-x", (x * 3.5).toFixed(2) + "px");
            ownerScout.style.setProperty("--scout-look-y", (y * 2.5).toFixed(2) + "px");
            ownerScout.style.setProperty("--scout-glass-turn", (x * 4).toFixed(2) + "deg");
        });
    }

    button.disabled = false;
    button.addEventListener("click", () => {
        if (hero.dataset.scoutActive === "true") button.classList.add("is-peeking");
    });
    button.addEventListener("animationend", event => {
        if (event.animationName === "owner-scout-peek") button.classList.remove("is-peeking");
    });
    hero.addEventListener("pointermove", lookAtPointer, {passive: true});
    hero.addEventListener("pointerleave", resetGaze);
    hero.addEventListener("pointercancel", resetGaze);
    document.addEventListener("visibilitychange", syncEffects);
    document.addEventListener("privatefind:motionchange", syncEffects);
    reducedMotion.addEventListener("change", syncEffects);
    finePointer.addEventListener("change", syncEffects);
    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(entries => {
            inView = entries[0].isIntersecting && entries[0].intersectionRatio >= 0.15;
            syncEffects();
        }, {threshold: 0.15});
        observer.observe(ownerScout);
    }
    // Static fallback when visibility observation is unavailable.
    syncEffects();
}

// One visibility-aware helper for decorative companions; no workflow or field data.
const companionScenes = [...document.querySelectorAll("[data-mascot-motion]")];
if (companionScenes.length) {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const finePointer = window.matchMedia("(any-hover: hover) and (any-pointer: fine)");
    const visible = new WeakMap();
    const lookout = document.querySelector("[data-chirp-lookout]");
    const chirp = lookout?.querySelector(".login-illustration");
    let frame = 0;
    let pointer;

    function resetChirp() {
        if (frame) cancelAnimationFrame(frame);
        frame = 0;
        for (const name of ["--chirp-x", "--chirp-y", "--chirp-turn"]) {
            lookout?.style.removeProperty(name);
        }
    }

    function syncCompanions() {
        for (const scene of companionScenes) {
            scene.dataset.mascotActive = String(visible.get(scene) === true && !document.hidden && !motion.matches && window.privateFindMotion?.paused !== true);
        }
        if (chirp?.dataset.mascotActive !== "true" || !finePointer.matches) resetChirp();
    }

    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(entries => {
            for (const entry of entries) {
                visible.set(entry.target, entry.isIntersecting && entry.intersectionRatio >= 0.15);
            }
            syncCompanions();
        }, {threshold: 0.15});
        companionScenes.forEach(scene => observer.observe(scene));
    }
    document.addEventListener("visibilitychange", syncCompanions);
    document.addEventListener("privatefind:motionchange", syncCompanions);
    motion.addEventListener("change", syncCompanions);
    finePointer.addEventListener("change", syncCompanions);

    if (lookout && chirp) {
        // Only focus identities are observed. Never inspect input values or key events.
        lookout.addEventListener("focusin", event => {
            lookout.dataset.chirpFocus = ["email", "password"].includes(event.target.id) ? event.target.id : "";
            resetChirp();
        });
        lookout.addEventListener("focusout", () => {
            lookout.dataset.chirpFocus = "";
            resetChirp();
        });
        lookout.addEventListener("pointerleave", resetChirp);
        lookout.addEventListener("pointercancel", resetChirp);
        lookout.addEventListener("pointermove", event => {
            if (event.pointerType !== "mouse" || !finePointer.matches || lookout.dataset.chirpFocus || chirp.dataset.mascotActive !== "true") return;
            pointer = {x: event.clientX, y: event.clientY};
            if (frame) return;
            frame = requestAnimationFrame(() => {
                frame = 0;
                if (chirp.dataset.mascotActive !== "true") return;
                const bounds = chirp.getBoundingClientRect();
                const clamp = value => Math.max(-1, Math.min(1, value));
                const x = clamp((pointer.x - bounds.left - bounds.width / 2) / bounds.width);
                const y = clamp((pointer.y - bounds.top - bounds.height / 2) / bounds.height);
                lookout.style.setProperty("--chirp-x", (x * 3).toFixed(2) + "px");
                lookout.style.setProperty("--chirp-y", (y * 2).toFixed(2) + "px");
                lookout.style.setProperty("--chirp-turn", (x * 3).toFixed(2) + "deg");
            });
        }, {passive: true});
    }
    syncCompanions();
}
