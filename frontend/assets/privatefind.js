window.privateFind = {
    humanize(value) {
        return String(value ?? "Unknown")
            .replaceAll("_", " ")
            .replace(/\b\w/g, letter => letter.toUpperCase());
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
    const isOperator = document.body.classList.contains("role-admin");
    if (!isOperator && document.querySelector("[data-requires-ai]")) {
        aiStatus.hidden = false;
    }

    function showAIStatus({provider, available, mock_reporting_enabled}, availabilityError = "") {
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
