const TOKEN_KEY = "cm_token";
const STATUS_PRIORITY = { "Status": "red", "Restarts": "red", "Resources": "yellow", "Disk": "yellow", "Network": "yellow", "Logs": "yellow", "Updates": "yellow" };

document.addEventListener("DOMContentLoaded", init);

function init() {
    if (localStorage.getItem(TOKEN_KEY)) {
        showApp();
    } else {
        document.getElementById("auth-screen").classList.remove("hidden");
    }
}

function login() {
    const token = document.getElementById("token-input").value;
    localStorage.setItem(TOKEN_KEY, token);
    document.getElementById("auth-screen").classList.add("hidden");
    showApp();
}

function logout() {
    localStorage.removeItem(TOKEN_KEY);
    location.reload();
}

async function apiFetch(path, opts = {}) {
    const token = localStorage.getItem(TOKEN_KEY) ?? "";
    const res = await fetch(path, {
        ...opts,
        headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json", ...(opts.headers || {}) }
    });
    if (res.status === 401) logout();
    return res;
}

async function showApp() {
    document.getElementById("app-screen").classList.remove("hidden");
    refreshDashboard();
    setInterval(refreshDashboard, 30000); // Poll every 30s
}

async function refreshDashboard() {
    try {
        const [dockerRes, stateRes] = await Promise.all([
            apiFetch("/api/containers"), apiFetch("/api/state")
        ]);

        const dockerList = await dockerRes.json();
        const state = await stateRes.json();

        const issueMap = state.container_issues ?? {};
        const updateCache = state.updates ?? {};

        const containers = dockerList.map(c => {
            const name = c.Names.replace(/^\//, "");
            const issues = issueMap[name] ? issueMap[name].split(",").map(s => s.trim()) : [];

            let color = "bg-green-500/10 border-green-500/50";
            let indicator = "bg-green-500";

            for (const issue of issues) {
                if (STATUS_PRIORITY[issue.split(":")[0]] === "red") { color = "bg-red-500/10 border-red-500/50"; indicator = "bg-red-500"; break; }
                if (STATUS_PRIORITY[issue.split(":")[0]] === "yellow") { color = "bg-yellow-500/10 border-yellow-500/50"; indicator = "bg-yellow-500"; }
            }

            const cacheKey = (c.Image || "").replace(/\//g, "_");
            const updateObj = Object.values(updateCache).find(e => e?.image_ref?.replace(/\//g, "_") === cacheKey);
            const hasUpdate = updateObj && updateObj.data && updateObj.data.exit_code === 100;

            return `
                <div class="p-5 rounded-xl border ${color} transition">
                    <div class="flex justify-between items-start mb-2">
                        <h3 class="font-bold text-lg flex items-center gap-2">
                            <span class="w-3 h-3 rounded-full ${indicator}"></span> ${name}
                        </h3>
                        <span class="text-xs text-gray-400">${c.Status}</span>
                    </div>
                    ${issues.length > 0 ? `<p class="text-sm text-gray-300 mt-2"><strong>Issues:</strong> ${issues.join(", ")}</p>` : `<p class="text-sm text-gray-400 mt-2">No active issues.</p>`}
                    ${hasUpdate ? `
                        <div class="mt-4 pt-4 border-t border-gray-700 flex justify-between items-center">
                            <span class="text-sm text-yellow-400">Update Available</span>
                            <button onclick="updateContainer('${name}')" class="bg-yellow-600 hover:bg-yellow-500 text-white text-xs px-3 py-1 rounded">Update Now</button>
                        </div>
                    ` : ''}
                </div>
            `;
        }).join("");

        document.getElementById("dashboard").innerHTML = containers;
    } catch (e) {
        console.error("Dashboard refresh failed", e);
    }
}

function triggerRun() {
    alert("Checks triggered in background. Dashboard will update automatically in ~30 seconds.");
    apiFetch("/api/run", { method: "POST" }).catch(e => console.error(e));
}

async function updateContainer(name) {
    if(!confirm(`Are you sure you want to pull and recreate ${name}?`)) return;
    alert(`Updating ${name}... This may take a minute.`);
    const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
    const data = await res.json();
    if(data.exit_code !== 0) alert("Update failed:\n" + data.error);
    else alert("Update successful!");
    refreshDashboard();
}
