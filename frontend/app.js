const TOKEN_KEY = "cm_token";
const STATUS_PRIORITY = { "Status": "red", "Restarts": "red", "Resources": "yellow", "Disk": "yellow", "Network": "yellow", "Logs": "yellow", "Updates": "yellow" };

let pendingUpdates = []; // Tracks containers that have updates

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
        const [dockerRes, stateRes, statsRes] = await Promise.all([
            apiFetch("/api/containers"),
            apiFetch("/api/state"),
            apiFetch("/api/host-stats")
        ]);
        const dockerList = await dockerRes.json();
        const state = await stateRes.json();
        if (statsRes.ok) {
            const stats = await statsRes.json();
            document.getElementById("stat-cpu").innerText = stats.cpu_load;
            document.getElementById("stat-mem").innerText = stats.memory.percent;
            document.getElementById("stat-mem-detail").innerText = `${stats.memory.used} / ${stats.memory.total}`;
            document.getElementById("stat-disk").innerText = stats.disk.percent;
            document.getElementById("stat-disk-detail").innerText = `${stats.disk.used} / ${stats.disk.size}`;
            document.getElementById("stat-disk-fs").innerText = stats.disk.fs;
        }
        const issueMap = state.container_issues ?? {};
        const updateCache = state.updates ?? {};
        pendingUpdates = [];
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
            if (hasUpdate) pendingUpdates.push(name);

            return `
                <div class="p-5 rounded-xl border ${color} transition flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-start mb-2">
                            <h3 class="font-bold text-lg flex items-center gap-2 truncate" title="${name}">
                                <span class="w-3 h-3 flex-shrink-0 rounded-full ${indicator}"></span> <span class="truncate">${name}</span>
                            </h3>
                            <div class="flex items-center gap-1 ml-2">
                                <button onclick="controlContainer('start', '${name}')" class="text-gray-500 hover:text-green-400 px-1 transition" title="Start Container">▶</button>
                                <button onclick="controlContainer('stop', '${name}')" class="text-gray-500 hover:text-red-400 px-1 transition" title="Stop Container">⏹</button>
                                <button onclick="controlContainer('restart', '${name}')" class="text-gray-500 hover:text-cyan-400 px-1 transition" title="Restart Container">🔄</button>
                                <span class="text-xs text-gray-400 ml-1 px-2 py-1 bg-gray-800 rounded whitespace-nowrap">${c.Status.split(' ')[0]}</span>
                            </div>
                        </div>
                        ${issues.length > 0 ? `<p class="text-sm text-gray-300 mt-2"><strong>Issues:</strong> ${issues.join(", ")}</p>` : `<p class="text-sm text-gray-400 mt-2">No active issues.</p>`}
                    </div>

                    <div class="mt-4 pt-4 border-t border-gray-700 flex flex-wrap gap-2 justify-between items-center">
                        <div class="flex gap-2 w-full">
                            <button onclick="viewLogs('${name}')" class="flex-1 bg-gray-700 hover:bg-gray-600 text-white text-xs px-3 py-2 rounded transition flex justify-center items-center gap-2">
                                📜 Logs
                            </button>
                            ${hasUpdate ? `
                                <button onclick="updateContainer('${name}', this)" class="flex-1 bg-yellow-600 hover:bg-yellow-500 text-white text-xs px-3 py-2 rounded shadow-[0_0_10px_rgba(202,138,4,0.4)] transition flex justify-center items-center gap-2">
                                    🔄 Update Now
                                </button>
                            ` : `
                                <button onclick="updateContainer('${name}', this)" class="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs px-3 py-2 rounded transition flex justify-center items-center gap-2" title="Force Pull & Recreate">
                                    🔄 Force Update
                                </button>
                            `}
                        </div>
                    </div>
                </div>
            `;
        }).join("");

        document.getElementById("dashboard-view").innerHTML = containers;

        const updateAllBtn = document.getElementById("update-all-btn");
        if (pendingUpdates.length > 0) {
            updateAllBtn.classList.remove("hidden");
            updateAllBtn.innerText = `🔄 Update All (${pendingUpdates.length})`;
        } else {
            updateAllBtn.classList.add("hidden");
        }

    } catch (e) {
        console.error("Dashboard refresh failed", e);
    }
}

async function triggerRun() {
    const btn = document.getElementById("run-check-btn");
    const originalText = btn.innerHTML;
    btn.innerHTML = "⏳ Running...";
    btn.disabled = true;

    try {
        await apiFetch("/api/run", { method: "POST" });
    } catch (e) {
        console.error("Run check failed", e);
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
    refreshDashboard();
}

async function updateContainer(name, btnElement) {
    if(!confirm(`Are you sure you want to pull and recreate ${name}?`)) return;

    const originalText = btnElement.innerHTML;
    btnElement.innerHTML = "⏳ Updating...";
    btnElement.disabled = true;

    try {
        const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
            alert("Update failed:\n" + (data.detail || res.statusText));
        } else if (data.exit_code !== 0) {
            alert("Docker Compose failed:\n" + (data.error || "Unknown error") + "\n\nOutput:\n" + data.output);
        } else {
            await apiFetch("/api/run", { method: "POST" });
        }
    } catch (e) {
        alert("Network or API request failed:\n" + e.message);
    }

    btnElement.innerHTML = originalText;
    btnElement.disabled = false;
    refreshDashboard();
}

async function controlContainer(action, name) {
    if (!confirm(`Are you sure you want to ${action.toUpperCase()} ${name}?`)) return;
    try {
        const res = await apiFetch(`/api/containers/${action}/${name}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.exit_code !== 0) {
            alert(`Failed to ${action} ${name}:\n` + (data.error || data.detail || "Unknown error"));
        }
    } catch (e) {
        alert("Network error:\n" + e.message);
    }
    refreshDashboard();
}

async function updateAll() {
    if (!confirm(`Are you sure you want to update all ${pendingUpdates.length} eligible containers?`)) return;

    const btn = document.getElementById("update-all-btn");
    const originalText = btn.innerHTML;
    btn.innerHTML = "⏳ Updating All...";
    btn.disabled = true;
    let successCount = 0;
    let failCount = 0;
    for (const name of pendingUpdates) {
        try {
            const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
            const data = await res.json();
            if (res.ok && data.exit_code === 0) {
                successCount++;
            } else {
                failCount++;
                console.error(`Failed to update ${name}:`, data);
            }
        } catch (e) {
            failCount++;
            console.error(`Network error updating ${name}:`, e);
        }
    }
    alert(`Update All Complete.\nSuccess: ${successCount}\nFailed: ${failCount}`);
    await apiFetch("/api/run", { method: "POST" });
    btn.innerHTML = originalText;
    btn.disabled = false;
    refreshDashboard();
}

async function viewLogs(name) {
    document.getElementById("log-modal").classList.remove("hidden");
    document.getElementById("log-modal").classList.add("flex");
    document.getElementById("log-modal-title").innerText = `Logs: ${name}`;
    document.getElementById("log-modal-content").innerText = "Fetching logs...";

    try {
        const res = await apiFetch(`/api/container-logs/${name}`);
        const data = await res.json();
        document.getElementById("log-modal-content").textContent = data.output || "No logs available or command failed.";
    } catch (e) {
        document.getElementById("log-modal-content").innerText = "Error fetching logs from server.";
    }
}

function closeLogModal() {
    document.getElementById("log-modal").classList.add("hidden");
    document.getElementById("log-modal").classList.remove("flex");
    document.getElementById("log-modal-content").innerText = "";
}

// --- Tab & Settings Logic ---

function switchTab(tabName) {
    const views = ["dashboard", "settings", "applogs"];
    views.forEach(view => {
        const isTarget = view === tabName;
        document.getElementById(`${view}-view`).classList.toggle("hidden", !isTarget);
        const tab = document.getElementById(`tab-${view}`);
        tab.className = isTarget
            ? "text-cyan-400 font-bold transition"
            : "text-gray-400 hover:text-cyan-400 transition";
    });
    if (tabName === 'settings') loadConfig();
    if (tabName === 'applogs') loadAppLogs();
}

async function loadConfig() {
    try {
        const res = await apiFetch("/api/config");
        const data = await res.json();
        if (res.ok) {
            document.getElementById("config-editor").value = data.yaml_text;
        } else {
            document.getElementById("config-editor").value = "# Error loading config: " + data.detail;
        }
    } catch (e) {
        console.error("Failed to load config", e);
    }
}

async function saveConfig() {
    const yamlText = document.getElementById("config-editor").value;
    const statusText = document.getElementById("config-save-status");

    statusText.innerText = "⏳ Saving...";
    statusText.className = "text-sm text-yellow-400";

    try {
        const res = await apiFetch("/api/config", {
            method: "PUT",
            body: JSON.stringify({ yaml_text: yamlText })
        });

        if (res.ok) {
            statusText.innerText = "✅ Saved successfully!";
            statusText.className = "text-sm text-green-400";
            setTimeout(() => statusText.innerText = "", 3000);
        } else {
            const data = await res.json();
            statusText.innerText = "❌ Error: " + (data.detail || "Invalid YAML");
            statusText.className = "text-sm text-red-400";
        }
    } catch (e) {
        statusText.innerText = "❌ Network Error";
        statusText.className = "text-sm text-red-400";
    }
}

// --- App Logs & Prune Logic ---

async function loadAppLogs() {
    const logBox = document.getElementById("app-logs-content");
    logBox.innerText = "Loading logs...";
    try {
        const res = await apiFetch("/api/logs");
        const data = await res.json();
        if (res.ok && data.lines) {
            logBox.textContent = data.lines.join("\n") || "Log file is empty.";
            // Auto-scroll to bottom
            logBox.scrollTop = logBox.scrollHeight;
        } else {
            logBox.textContent = "Failed to load logs.";
        }
    } catch (e) {
        logBox.textContent = "Network error loading logs.";
    }
}

async function systemPrune() {
    if (!confirm("⚠️ WARNING: This will remove ALL stopped containers, unused networks, and unused images.\n\nAre you sure you want to proceed?")) return;

    const btn = document.getElementById("prune-btn");
    const originalText = btn.innerHTML;
    btn.innerHTML = "⏳ Pruning System...";
    btn.disabled = true;

    try {
        const res = await apiFetch("/api/prune", { method: "POST" });
        const data = await res.json();

        if (res.ok && data.exit_code === 0) {
            alert("System Prune Complete!\n\nOutput:\n" + data.output);
            // Refresh dashboard to update host disk stats
            refreshDashboard();
        } else {
            alert("Prune failed:\n" + (data.output || "Unknown error"));
        }
    } catch (e) {
        alert("Network error during prune:\n" + e.message);
    }

    btn.innerHTML = originalText;
    btn.disabled = false;
}
