const TOKEN_KEY = "cm_token";
const STATUS_PRIORITY = { "Status": "red", "Restarts": "red", "Resources": "yellow", "Disk": "yellow", "Network": "yellow", "Logs": "yellow", "Updates": "yellow" };

let pendingUpdates = [];

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

// --- UI Utility Functions ---

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    let styleClasses = '';
    let icon = '';
    if (type === 'success') {
        styleClasses = 'bg-emerald-500/10 border-emerald-500/50 text-emerald-400';
        icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;
    } else if (type === 'error') {
        styleClasses = 'bg-red-500/10 border-red-500/50 text-red-400';
        icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`;
    } else if (type === 'info') {
        styleClasses = 'bg-blue-500/10 border-blue-500/50 text-blue-400';
        icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
    }
    toast.className = `flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-md shadow-lg transform transition-all duration-300 translate-y-10 opacity-0 pointer-events-auto ${styleClasses}`;
    toast.innerHTML = `${icon} <span class="text-sm font-medium">${message}</span>`;
    container.appendChild(toast);
    requestAnimationFrame(() => {
        toast.classList.remove('translate-y-10', 'opacity-0');
    });
    setTimeout(() => {
        toast.classList.add('opacity-0', 'translate-y-2');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function customConfirm(title, message) {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirm-modal');
        const box = document.getElementById('confirm-modal-box');
        document.getElementById('confirm-title').innerText = title;
        document.getElementById('confirm-message').innerText = message;
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        requestAnimationFrame(() => {
            modal.classList.remove('opacity-0');
            box.classList.remove('scale-95');
        });
        const btnYes = document.getElementById('confirm-yes');
        const btnNo = document.getElementById('confirm-no');
        const cleanup = () => {
            modal.classList.add('opacity-0');
            box.classList.add('scale-95');
            setTimeout(() => {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
            }, 200);
            btnYes.onclick = null;
            btnNo.onclick = null;
        };
        btnYes.onclick = () => { cleanup(); resolve(true); };
        btnNo.onclick = () => { cleanup(); resolve(false); };
    });
}

// --- Core App Logic ---

async function showApp() {
    document.getElementById("app-screen").classList.remove("hidden");
    refreshDashboard();
    setInterval(refreshDashboard, 30000);
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
            const isRunning = c.Status.startsWith("Up");
            let borderColor = "border-gray-700/50";
            let statusPill = isRunning ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Running</span>`
                                       : `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-gray-500/10 text-gray-400 border border-gray-500/20">${c.Status.split(' ')[0]}</span>`;

            for (const issue of issues) {
                if (STATUS_PRIORITY[issue.split(":")[0]] === "red") {
                    borderColor = "border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.1)]";
                    statusPill = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/20">Error</span>`;
                    break;
                }
                if (STATUS_PRIORITY[issue.split(":")[0]] === "yellow") {
                    borderColor = "border-yellow-500/50";
                    if(isRunning) statusPill = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">Warning</span>`;
                }
            }

            const cacheKey = (c.Image || "").replace(/\//g, "_");
            const updateObj = Object.values(updateCache).find(e => e?.image_ref?.replace(/\//g, "_") === cacheKey);
            const hasUpdate = updateObj && updateObj.data && updateObj.data.exit_code === 100;
            if (hasUpdate) pendingUpdates.push(name);

            return `
                <div class="p-5 rounded-2xl border ${borderColor} bg-gray-800/30 backdrop-blur-sm transition hover:bg-gray-800/50 flex flex-col justify-between">
                    <div>
                        <div class="flex justify-between items-start mb-3">
                            <h3 class="font-bold text-lg text-white truncate pr-2" title="${name}">${name}</h3>
                            <div class="flex items-center gap-2">
                                <div class="flex items-center bg-gray-900/80 rounded-lg border border-gray-700 p-0.5">
                                    <button onclick="controlContainer('start', '${name}')" class="text-gray-500 hover:text-emerald-400 p-1 rounded transition" title="Start"><svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path d="M4 4l12 6-12 6V4z"></path></svg></button>
                                    <button onclick="controlContainer('stop', '${name}')" class="text-gray-500 hover:text-red-400 p-1 rounded transition" title="Stop"><svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><rect x="4" y="4" width="12" height="12"></rect></svg></button>
                                    <button onclick="controlContainer('restart', '${name}')" class="text-gray-500 hover:text-cyan-400 p-1 rounded transition" title="Restart"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg></button>
                                </div>
                                ${statusPill}
                            </div>
                        </div>
                        ${issues.length > 0 ? `<p class="text-xs text-gray-400 mt-2 leading-relaxed"><strong>Alerts:</strong> ${issues.join(", ")}</p>` : `<p class="text-xs text-gray-500 mt-2">Operating normally.</p>`}
                    </div>

                    <div class="mt-5 pt-4 border-t border-gray-700/50 flex gap-3">
                        <button onclick="viewLogs('${name}')" class="flex-1 bg-gray-900/50 hover:bg-gray-700 text-gray-300 border border-gray-700 text-xs font-medium px-3 py-2 rounded-lg transition flex justify-center items-center gap-2">
                            <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                            Logs
                        </button>
                        ${hasUpdate ? `
                            <button onclick="updateContainer('${name}', this)" class="flex-1 bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 text-xs font-medium px-3 py-2 rounded-lg transition flex justify-center items-center gap-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                                Update
                            </button>
                        ` : `
                            <button onclick="updateContainer('${name}', this)" class="flex-1 bg-gray-900/50 hover:bg-gray-700 text-gray-400 border border-gray-700 text-xs font-medium px-3 py-2 rounded-lg transition flex justify-center items-center gap-2" title="Force Pull & Recreate">
                                <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                                Pull
                            </button>
                        `}
                    </div>
                </div>
            `;
        }).join("");

        document.getElementById("dashboard-view").innerHTML = containers;

        const updateAllBtn = document.getElementById("update-all-btn");
        if (pendingUpdates.length > 0) {
            updateAllBtn.classList.remove("hidden");
            document.getElementById("update-count").innerText = pendingUpdates.length;
        } else {
            updateAllBtn.classList.add("hidden");
        }

    } catch (e) {
        console.error("Dashboard refresh failed", e);
    }
}

async function triggerRun(force = false) {
    const btnId = force ? "force-check-btn" : "run-check-btn";
    const btn = document.getElementById(btnId);
    if (!btn) return;
    const originalContent = btn.innerHTML;
    btn.innerHTML = `<svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${force ? 'Forcing...' : 'Running...'}`;
    btn.disabled = true;
    try {
        const endpoint = force ? "/api/run?force=true" : "/api/run";
        await apiFetch(endpoint, { method: "POST" });
        showToast(force ? "Forced check completed (Cache bypassed)" : "Check completed successfully", "success");
    } catch (e) {
        showToast("Check failed to run", "error");
    }
    btn.innerHTML = originalContent;
    btn.disabled = false;
    refreshDashboard();
}

async function updateContainer(name, btnElement) {
    const confirmed = await customConfirm("Update Container", `Are you sure you want to pull the latest image and recreate ${name}?`);
    if (!confirmed) return;
    const originalContent = btnElement.innerHTML;
    btnElement.innerHTML = `<svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Updating`;
    btnElement.disabled = true;
    showToast(`Pulling updates for ${name}...`, "info");
    try {
        const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
            showToast("Update failed: " + (data.detail || res.statusText), "error");
        } else if (data.exit_code !== 0) {
            showToast("Docker Compose failed. Check logs.", "error");
            console.error(data.output);
        } else {
            showToast(`${name} updated successfully!`, "success");
            await apiFetch("/api/run", { method: "POST" });
        }
    } catch (e) {
        showToast("Network error during update.", "error");
    }
    btnElement.innerHTML = originalContent;
    btnElement.disabled = false;
    refreshDashboard();
}

async function controlContainer(action, name) {
    const actionCap = action.charAt(0).toUpperCase() + action.slice(1);
    const confirmed = await customConfirm(`${actionCap} Container`, `Are you sure you want to ${action} ${name}?`);
    if (!confirmed) return;

    showToast(`Sending ${action} command to ${name}...`, "info");

    try {
        const res = await apiFetch(`/api/containers/${action}/${name}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok || data.exit_code !== 0) {
            showToast(`Failed to ${action} ${name}: ` + (data.error || data.detail), "error");
        } else {
            showToast(`${name} successfully ${action}ed.`, "success");
        }
    } catch (e) {
        showToast("Network error executing command.", "error");
    }
    refreshDashboard();
}

async function updateAll() {
    const confirmed = await customConfirm("Update All", `Are you sure you want to pull and recreate all ${pendingUpdates.length} eligible containers?`);
    if (!confirmed) return;

    const btn = document.getElementById("update-all-btn");
    const originalContent = btn.innerHTML;
    btn.innerHTML = `<svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Updating All...`;
    btn.disabled = true;
    let successCount = 0;
    let failCount = 0;
    showToast(`Starting mass update for ${pendingUpdates.length} containers...`, "info");
    for (const name of pendingUpdates) {
        try {
            const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
            const data = await res.json();
            if (res.ok && data.exit_code === 0) {
                successCount++;
            } else {
                failCount++;
            }
        } catch (e) {
            failCount++;
        }
    }
    if (failCount === 0) {
        showToast(`Successfully updated all ${successCount} containers!`, "success");
    } else {
        showToast(`Update finished: ${successCount} succeeded, ${failCount} failed.`, "error");
    }

    await apiFetch("/api/run", { method: "POST" });
    btn.innerHTML = originalContent;
    btn.disabled = false;
    refreshDashboard();
}

async function viewLogs(name) {
    const modal = document.getElementById("log-modal");
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    requestAnimationFrame(() => modal.classList.remove("opacity-0"));
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
    const modal = document.getElementById("log-modal");
    modal.classList.add("opacity-0");
    setTimeout(() => {
        modal.classList.add("hidden");
        modal.classList.remove("flex");
        document.getElementById("log-modal-content").innerText = "";
    }, 200);
}

// --- Tab & Settings Logic ---

function switchTab(tabName) {
    const views = ["dashboard", "settings", "applogs"];
    views.forEach(view => {
        const isTarget = view === tabName;
        document.getElementById(`${view}-view`).classList.toggle("hidden", !isTarget);
        const tab = document.getElementById(`tab-${view}`);
        if(isTarget) {
            tab.className = "px-4 py-2 rounded-lg bg-gray-800 text-cyan-400 font-medium transition";
        } else {
            tab.className = "px-4 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800/50 font-medium transition";
        }
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
        showToast("Failed to load config", "error");
    }
}

async function saveConfig() {
    const yamlText = document.getElementById("config-editor").value;
    const statusText = document.getElementById("config-save-status");

    statusText.innerText = "⏳ Saving...";
    statusText.className = "text-sm font-medium text-yellow-400";

    try {
        const res = await apiFetch("/api/config", {
            method: "PUT",
            body: JSON.stringify({ yaml_text: yamlText })
        });

        if (res.ok) {
            statusText.innerText = "";
            showToast("Configuration saved successfully!", "success");
        } else {
            const data = await res.json();
            statusText.innerText = "";
            showToast("Invalid YAML Format", "error");
        }
    } catch (e) {
        statusText.innerText = "";
        showToast("Network error saving config.", "error");
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
            logBox.scrollTop = logBox.scrollHeight;
        } else {
            logBox.textContent = "Failed to load logs.";
        }
    } catch (e) {
        logBox.textContent = "Network error loading logs.";
    }
}

async function systemPrune() {
    const confirmed = await customConfirm("System Prune", "⚠️ WARNING: This will remove ALL stopped containers, unused networks, and unused images. Are you sure you want to proceed?");
    if (!confirmed) return;
    showToast("Starting system prune. This may take a minute...", "info");

    try {
        const res = await apiFetch("/api/prune", { method: "POST" });
        const data = await res.json();

        if (res.ok && data.exit_code === 0) {
            showToast("System Prune Complete!", "success");
            refreshDashboard();
        } else {
            showToast("Prune failed. Check logs.", "error");
        }
    } catch (e) {
        showToast("Network error during prune.", "error");
    }
}
