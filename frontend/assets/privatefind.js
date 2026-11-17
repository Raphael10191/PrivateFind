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
