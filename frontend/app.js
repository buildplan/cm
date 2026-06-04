const TOKEN_KEY = "cm_token";
const STATUS_PRIORITY = {
	Status: "red",
	Restarts: "red",
	Resources: "yellow",
	Disk: "yellow",
	Network: "yellow",
	Logs: "yellow",
	Updates: "yellow",
};
const APP_VERSION = "dev";

let pendingUpdates = [];

document.addEventListener("DOMContentLoaded", init);

function init() {
	if (localStorage.getItem(TOKEN_KEY)) {
		showApp();
	} else {
		fetch("/api/auth/status")
			.then((r) => r.json())
			.then((status) => {
				if (!status.auth_required) {
					showApp();
				} else {
					document.getElementById("auth-screen").classList.remove("hidden");
					const passkeyBtn = document.getElementById("btn-login-passkey");
					const tokenSection = document.getElementById("section-login-token");
					const orDivider = document.getElementById("divider-or");

					if (status.has_passkeys) passkeyBtn.classList.remove("hidden");
					else passkeyBtn.classList.add("hidden");

					if (status.token_auth_enabled) {
						tokenSection.classList.remove("hidden");
						if (status.has_passkeys) orDivider.classList.remove("hidden");
						else orDivider.classList.add("hidden");
					} else {
						tokenSection.classList.add("hidden");
						orDivider.classList.add("hidden");
					}
				}
			})
			.catch(() => {
				document.getElementById("auth-screen").classList.remove("hidden");
				document
					.getElementById("section-login-token")
					.classList.remove("hidden");
			});
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

// --- WebAuthn Helpers ---
function base64urlToBuffer(base64url) {
	const padding = "=".repeat((4 - (base64url.length % 4)) % 4);
	const base64 = (base64url + padding).replace(/-/g, "+").replace(/_/g, "/");
	const rawData = window.atob(base64);
	const outputArray = new Uint8Array(rawData.length);
	for (let i = 0; i < rawData.length; ++i) {
		outputArray[i] = rawData.charCodeAt(i);
	}
	return outputArray.buffer;
}

function bufferToBase64url(buffer) {
	const bytes = new Uint8Array(buffer);
	let str = "";
	for (const charCode of bytes) {
		str += String.fromCharCode(charCode);
	}
	const base64String = window.btoa(str);
	return base64String.replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

async function loginWithPasskey() {
	try {
		const res = await fetch("/api/auth/login/generate-options");
		const options = await res.json();

		options.challenge = base64urlToBuffer(options.challenge);
		if (options.allowCredentials) {
			options.allowCredentials.forEach((cred) => {
				cred.id = base64urlToBuffer(cred.id);
			});
		}

		const assertion = await navigator.credentials.get({ publicKey: options });

		const verifyRes = await fetch("/api/auth/login/verify", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				id: assertion.id,
				rawId: bufferToBase64url(assertion.rawId),
				type: assertion.type,
				response: {
					authenticatorData: bufferToBase64url(
						assertion.response.authenticatorData,
					),
					clientDataJSON: bufferToBase64url(assertion.response.clientDataJSON),
					signature: bufferToBase64url(assertion.response.signature),
					userHandle: assertion.response.userHandle
						? bufferToBase64url(assertion.response.userHandle)
						: null,
				},
			}),
		});

		const verifyData = await verifyRes.json();
		if (verifyRes.ok && verifyData.token) {
			localStorage.setItem(TOKEN_KEY, verifyData.token);
			document.getElementById("auth-screen").classList.add("hidden");
			showApp();
			showToast("Login successful via Passkey");
		} else {
			showToast(verifyData.detail || "Verification failed", "error");
		}
	} catch (e) {
		console.error(e);
		showToast("Passkey login cancelled or failed.", "error");
	}
}

async function registerPasskey() {
	try {
		showToast("Starting passkey registration...", "info");
		const res = await apiFetch("/api/auth/register/generate-options");
		if (!res.ok) {
			showToast("Failed to fetch registration options", "error");
			return;
		}
		const options = await res.json();

		options.challenge = base64urlToBuffer(options.challenge);
		options.user.id = base64urlToBuffer(options.user.id);
		if (options.excludeCredentials) {
			options.excludeCredentials.forEach((cred) => {
				cred.id = base64urlToBuffer(cred.id);
			});
		}

		const credential = await navigator.credentials.create({
			publicKey: options,
		});

		const verifyRes = await apiFetch("/api/auth/register/verify", {
			method: "POST",
			body: JSON.stringify({
				id: credential.id,
				rawId: bufferToBase64url(credential.rawId),
				type: credential.type,
				response: {
					attestationObject: bufferToBase64url(
						credential.response.attestationObject,
					),
					clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
				},
			}),
		});

		if (verifyRes.ok) {
			showToast("Passkey registered successfully!", "success");
		} else {
			const err = await verifyRes.json();
			showToast(err.detail || "Failed to verify registration", "error");
		}
	} catch (e) {
		console.error(e);
		showToast("Passkey registration cancelled or failed.", "error");
	}
}

function isNewerVersion(localVer, upstreamVer) {
	if (!localVer.match(/v?\d+\.\d+\.\d+/)) return false;
	const l = localVer.replace("v", "").split(".").map(Number);
	const u = upstreamVer.replace("v", "").split(".").map(Number);
	for (let i = 0; i < Math.max(l.length, u.length); i++) {
		if ((u[i] || 0) > (l[i] || 0)) return true;
		if ((u[i] || 0) < (l[i] || 0)) return false;
	}
	return false;
}

async function fetchAppVersion() {
	const versionEl = document.getElementById("app-version");
	if (!versionEl) return;
	versionEl.innerHTML = APP_VERSION;
	try {
		const res = await fetch("https://api.github.com/repos/buildplan/cm/tags");
		if (res.ok) {
			const data = await res.json();
			if (data.length > 0 && data[0].name) {
				const upstreamVersion = data[0].name;
				if (isNewerVersion(APP_VERSION, upstreamVersion)) {
					versionEl.innerHTML = `
                        ${APP_VERSION}
                        <a href="https://github.com/buildplan/cm/pkgs/container/cm" target="_blank" rel="noopener noreferrer" class="ml-2 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/20 transition cursor-pointer" title="View latest image on GitHub">
                            Update Available: ${upstreamVersion}
                        </a>
                    `;
				}
			}
		}
	} catch (e) {
		console.error("Failed to check for upstream updates:", e);
	}
}

async function apiFetch(path, opts = {}) {
	const token = localStorage.getItem(TOKEN_KEY) ?? "";
	const res = await fetch(path, {
		...opts,
		headers: {
			Authorization: `Bearer ${token}`,
			"Content-Type": "application/json",
			...(opts.headers || {}),
		},
	});
	if (res.status === 401) logout();
	return res;
}

// --- UI Utility Functions ---

function showToast(message, type = "success") {
	const container = document.getElementById("toast-container");
	const toast = document.createElement("div");
	let styleClasses = "";
	let icon = "";
	if (type === "success") {
		styleClasses = "bg-emerald-500/10 border-emerald-500/50 text-emerald-400";
		icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>`;
	} else if (type === "error") {
		styleClasses = "bg-red-500/10 border-red-500/50 text-red-400";
		icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`;
	} else if (type === "info") {
		styleClasses = "bg-blue-500/10 border-blue-500/50 text-blue-400";
		icon = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;
	}
	toast.className = `flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-md shadow-lg transform transition-all duration-300 translate-y-10 opacity-0 pointer-events-auto ${styleClasses}`;
	toast.innerHTML = `${icon} <span class="text-sm font-medium">${message}</span>`;
	container.appendChild(toast);
	requestAnimationFrame(() => {
		toast.classList.remove("translate-y-10", "opacity-0");
	});
	setTimeout(() => {
		toast.classList.add("opacity-0", "translate-y-2");
		setTimeout(() => toast.remove(), 300);
	}, 4000);
}

function customConfirm(title, message) {
	return new Promise((resolve) => {
		const modal = document.getElementById("confirm-modal");
		const box = document.getElementById("confirm-modal-box");
		document.getElementById("confirm-title").innerText = title;
		document.getElementById("confirm-message").innerText = message;
		modal.classList.remove("hidden");
		modal.classList.add("flex");
		requestAnimationFrame(() => {
			modal.classList.remove("opacity-0");
			box.classList.remove("scale-95");
		});
		const btnYes = document.getElementById("confirm-yes");
		const btnNo = document.getElementById("confirm-no");
		const cleanup = () => {
			modal.classList.add("opacity-0");
			box.classList.add("scale-95");
			setTimeout(() => {
				modal.classList.add("hidden");
				modal.classList.remove("flex");
			}, 200);
			btnYes.onclick = null;
			btnNo.onclick = null;
		};
		btnYes.onclick = () => {
			cleanup();
			resolve(true);
		};
		btnNo.onclick = () => {
			cleanup();
			resolve(false);
		};
	});
}

// --- Core App Logic ---

let sseSource = null;

function setupSSE() {
	if (sseSource) sseSource.close();
	const token = localStorage.getItem(TOKEN_KEY) ?? "";
	sseSource = new EventSource(`/api/events?token=${token}`);

	sseSource.onmessage = (event) => {
		try {
			const data = JSON.parse(event.data);
			if (data.type === "state_changed" || data.type === "docker_event") {
				refreshDashboard();
			}
		} catch {}
	};

	sseSource.onerror = (e) => {
		console.error("SSE connection error", e);
	};
}

async function showApp() {
	const appScreen = document.getElementById("app-screen");
	appScreen.classList.remove("hidden");
	appScreen.classList.add("flex");
	refreshDashboard();
	fetchAppVersion();
	setupSSE();
}

async function refreshDashboard() {
	try {
		const [dockerRes, stateRes, statsRes] = await Promise.all([
			apiFetch("/api/containers"),
			apiFetch("/api/state"),
			apiFetch("/api/host-stats"),
		]);
		const dockerList = await dockerRes.json();
		const state = await stateRes.json();
		if (statsRes.ok) {
			const stats = await statsRes.json();
			document.getElementById("stat-cpu").innerText = stats.cpu_load;
			document.getElementById("stat-mem").innerText = stats.memory.percent;
			document.getElementById("stat-mem-detail").innerText =
				`${stats.memory.used} / ${stats.memory.total}`;
			document.getElementById("stat-disk").innerText = stats.disk.percent;
			document.getElementById("stat-disk-detail").innerText =
				`${stats.disk.used} / ${stats.disk.size}`;
			document.getElementById("stat-disk-fs").innerText = stats.disk.fs;
		}
		const issueMap = state.container_issues ?? {};
		pendingUpdates = [];
		const containers = dockerList
			.map((c) => {
				const name = c.Names.replace(/^\//, "");
				const issues = issueMap[name]
					? issueMap[name].split("|").map((s) => s.trim())
					: [];
				const isRunning = c.Status.startsWith("Up");
				let borderColor = "border-gray-700/50";
				let statusPill = isRunning
					? `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Running</span>`
					: `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-gray-500/10 text-gray-400 border border-gray-500/20">${c.Status.split(" ")[0]}</span>`;

				for (const issue of issues) {
					if (STATUS_PRIORITY[issue.split(":")[0]] === "red") {
						borderColor =
							"border-red-500/50 shadow-[0_0_15px_rgba(239,68,68,0.2)] bg-red-500/5";
						statusPill = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-500/10 text-red-400 border border-red-500/20 animate-pulse shadow-[0_0_10px_rgba(239,68,68,0.3)]">Error</span>`;
						break;
					}
					if (STATUS_PRIORITY[issue.split(":")[0]] === "yellow") {
						borderColor =
							"border-yellow-500/50 shadow-[0_0_10px_rgba(234,179,8,0.1)] bg-yellow-500/5";
						if (isRunning)
							statusPill = `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 animate-pulse">Warning</span>`;
					}
				}

				const hasUpdate = issues.some((iss) =>
					iss.startsWith("Updates: Update available"),
				);
				if (hasUpdate) pendingUpdates.push(name);

				return `
                <div class="p-5 rounded-2xl border ${borderColor} bg-gray-800/20 backdrop-blur-xl transition-all duration-300 hover:-translate-y-1 hover:shadow-2xl hover:shadow-black/50 hover:bg-gray-800/50 flex flex-col justify-between group shadow-lg shadow-black/20">
                    <div>
                        <div class="flex justify-between items-start mb-3">
                            <h3 class="font-bold text-lg text-white truncate pr-2 group-hover:text-cyan-400 transition-colors" title="${name}">${name}</h3>
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

                    <div class="mt-5 pt-4 border-t border-gray-700/50 flex gap-3 opacity-80 group-hover:opacity-100 transition-opacity">
                        <button onclick="viewLogs('${name}')" class="flex-1 bg-gray-900/50 hover:bg-gray-700 text-gray-300 border border-gray-700 hover:border-gray-500 text-xs font-medium px-3 py-2 rounded-lg transition-all duration-200 flex justify-center items-center gap-2" title="Logs">
                            <svg class="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                        </button>
                        <button onclick="viewMetrics('${name}')" class="flex-1 bg-gray-900/50 hover:bg-gray-700 text-cyan-400 border border-gray-700 hover:border-gray-500 text-xs font-medium px-3 py-2 rounded-lg transition-all duration-200 flex justify-center items-center gap-2" title="Metrics">
                            <svg class="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z"></path></svg>
                        </button>
                        ${
													hasUpdate
														? `
                            <button onclick="updateContainer('${name}', this)" class="flex-[2] bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 text-xs font-medium px-3 py-2 rounded-lg transition flex justify-center items-center gap-2" title="Update">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                            </button>
                        `
														: `
                            <button onclick="updateContainer('${name}', this)" class="flex-[2] bg-gray-900/50 hover:bg-gray-700 text-gray-400 border border-gray-700 hover:border-gray-500 text-xs font-medium px-3 py-2 rounded-lg transition-all duration-200 flex justify-center items-center gap-2" title="Force Pull & Recreate">
                                <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                            </button>
                        `
												}
                    </div>
                </div>
            `;
			})
			.join("");

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
	btn.innerHTML = `<svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ${force ? "Forcing..." : "Running..."}`;
	btn.disabled = true;
	try {
		const endpoint = force ? "/api/run?force=true" : "/api/run";
		await apiFetch(endpoint, { method: "POST" });
		showToast(
			force
				? "Forced check completed (Cache bypassed)"
				: "Check completed successfully",
			"success",
		);
	} catch {
		showToast("Check failed to run", "error");
	}
	btn.innerHTML = originalContent;
	btn.disabled = false;
	refreshDashboard();
}

async function updateContainer(name, btnElement) {
	const confirmed = await customConfirm(
		"Update Container",
		`Are you sure you want to pull the latest image and recreate ${name}?`,
	);
	if (!confirmed) return;
	const originalContent = btnElement.innerHTML;
	btnElement.innerHTML = `<svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Updating`;
	btnElement.disabled = true;
	showToast(`Pulling updates for ${name}...`, "info");
	try {
		const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
		const data = await res.json();
		if (!res.ok) {
			showToast(`Update failed: ${data.detail || res.statusText}`, "error");
		} else if (data.exit_code !== 0) {
			showToast("Docker Compose failed. Check logs.", "error");
			console.error(data.output);
		} else {
			showToast(`${name} updated successfully!`, "success");
			await apiFetch("/api/run", { method: "POST" });
		}
	} catch {
		showToast("Network error during update.", "error");
	}
	btnElement.innerHTML = originalContent;
	btnElement.disabled = false;
	refreshDashboard();
}

async function controlContainer(action, name) {
	const actionCap = action.charAt(0).toUpperCase() + action.slice(1);
	const confirmed = await customConfirm(
		`${actionCap} Container`,
		`Are you sure you want to ${action} ${name}?`,
	);
	if (!confirmed) return;

	showToast(`Sending ${action} command to ${name}...`, "info");

	try {
		const res = await apiFetch(`/api/containers/${action}/${name}`, {
			method: "POST",
		});
		const data = await res.json();
		if (!res.ok || data.exit_code !== 0) {
			showToast(
				`Failed to ${action} ${name}: ${data.error || data.detail}`,
				"error",
			);
		} else {
			showToast(`${name} successfully ${action}ed.`, "success");
		}
	} catch {
		showToast("Network error executing command.", "error");
	}
	refreshDashboard();
}

async function updateAll() {
	const confirmed = await customConfirm(
		"Update All",
		`Are you sure you want to pull and recreate all ${pendingUpdates.length} eligible containers?`,
	);
	if (!confirmed) return;

	const btn = document.getElementById("update-all-btn");
	const originalContent = btn.innerHTML;
	btn.innerHTML = `<svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Updating All...`;
	btn.disabled = true;
	let successCount = 0;
	let failCount = 0;
	showToast(
		`Starting mass update for ${pendingUpdates.length} containers...`,
		"info",
	);
	for (const name of pendingUpdates) {
		try {
			const res = await apiFetch(`/api/update/${name}`, { method: "POST" });
			const data = await res.json();
			if (res.ok && data.exit_code === 0) {
				successCount++;
			} else {
				failCount++;
			}
		} catch (_e) {
			failCount++;
		}
	}
	if (failCount === 0) {
		showToast(
			`Successfully updated all ${successCount} containers!`,
			"success",
		);
	} else {
		showToast(
			`Update finished: ${successCount} succeeded, ${failCount} failed.`,
			"error",
		);
	}

	await apiFetch("/api/run", { method: "POST" });
	btn.innerHTML = originalContent;
	btn.disabled = false;
	refreshDashboard();
}

let currentLogContainer = null;
let logFollowInterval = null;
let isFollowingLogs = false;

async function viewLogs(name) {
	currentLogContainer = name;
	const modal = document.getElementById("log-modal");
	modal.classList.remove("hidden");
	modal.classList.add("flex");
	requestAnimationFrame(() => modal.classList.remove("opacity-0"));
	document.getElementById("log-modal-title").innerText = `Logs: ${name}`;
	document.getElementById("log-filter-input").value = "";

	await refreshCurrentLogs();
}

async function refreshCurrentLogs() {
	if (!currentLogContainer) return;
	const contentBox = document.getElementById("log-modal-content");
	const filterStr = document.getElementById("log-filter-input").value.trim();
	if (!isFollowingLogs) {
		contentBox.innerText = "Fetching logs...";
	}
	try {
		let url = `/api/container-logs/${currentLogContainer}`;
		if (filterStr) url += `?filter=${encodeURIComponent(filterStr)}`;
		const res = await apiFetch(url);
		const data = await res.json();
		contentBox.textContent =
			data.output || "No logs available or command failed.";
		contentBox.scrollTop = contentBox.scrollHeight;
	} catch (_e) {
		if (!isFollowingLogs) {
			contentBox.innerText = "Error fetching logs from server.";
		}
	}
}

function toggleFollowLogs() {
	const btn = document.getElementById("follow-logs-btn");
	isFollowingLogs = !isFollowingLogs;
	if (isFollowingLogs) {
		btn.classList.add(
			"text-emerald-400",
			"bg-gray-700",
			"border-emerald-500/50",
		);
		btn.classList.remove("text-gray-400");
		logFollowInterval = setInterval(refreshCurrentLogs, 2000);
		refreshCurrentLogs();
	} else {
		btn.classList.remove(
			"text-emerald-400",
			"bg-gray-700",
			"border-emerald-500/50",
		);
		btn.classList.add("text-gray-400");
		clearInterval(logFollowInterval);
		logFollowInterval = null;
	}
}

function closeLogModal() {
	if (isFollowingLogs) toggleFollowLogs();
	currentLogContainer = null;
	const modal = document.getElementById("log-modal");
	modal.classList.add("opacity-0");
	setTimeout(() => {
		modal.classList.add("hidden");
		modal.classList.remove("flex");
		document.getElementById("log-modal-content").innerText = "";
	}, 200);
}

// --- Metrics Logic ---
let metricsChartInstance = null;

async function viewMetrics(name) {
	const modal = document.getElementById("metrics-modal");
	modal.classList.remove("hidden");
	modal.classList.add("flex");
	requestAnimationFrame(() => modal.classList.remove("opacity-0"));
	document.getElementById("metrics-modal-title").innerText =
		`Metrics: ${name} (Last 24h)`;

	try {
		const res = await apiFetch(`/api/metrics/${name}`);
		const data = await res.json();
		renderChart(data);
	} catch (_e) {
		showToast("Failed to load metrics", "error");
	}
}

function closeMetricsModal() {
	const modal = document.getElementById("metrics-modal");
	modal.classList.add("opacity-0");
	setTimeout(() => {
		modal.classList.add("hidden");
		modal.classList.remove("flex");
	}, 200);
}

function renderChart(data) {
	const ctx = document.getElementById("metrics-chart").getContext("2d");

	if (metricsChartInstance) {
		metricsChartInstance.destroy();
	}

	let labels = [];
	let cpuData = [];
	let memData = [];

	if (data && data.length > 0) {
		labels = data.map((d) => {
			const date = new Date(d.t * 1000);
			return date.toLocaleTimeString([], {
				hour: "2-digit",
				minute: "2-digit",
			});
		});
		cpuData = data.map((d) => d.cpu);
		memData = data.map((d) => d.mem);
	} else {
		// Provide placeholder data so the chart framework still renders empty axes
		labels = ["No Data Yet"];
		cpuData = [0];
		memData = [0];
	}

	metricsChartInstance = new Chart(ctx, {
		type: "line",
		data: {
			labels: labels,
			datasets: [
				{
					label: "CPU Usage (%)",
					data: cpuData,
					borderColor: "#22d3ee",
					backgroundColor: "rgba(34, 211, 238, 0.1)",
					borderWidth: 2,
					pointRadius: 0,
					tension: 0.4,
					fill: true,
				},
				{
					label: "Memory Usage (%)",
					data: memData,
					borderColor: "#a855f7",
					backgroundColor: "rgba(168, 85, 247, 0.1)",
					borderWidth: 2,
					pointRadius: 0,
					tension: 0.4,
					fill: true,
				},
			],
		},
		options: {
			responsive: true,
			maintainAspectRatio: false,
			interaction: {
				mode: "index",
				intersect: false,
			},
			plugins: {
				legend: {
					labels: { color: "#9ca3af" },
				},
				tooltip: {
					backgroundColor: "rgba(17, 24, 39, 0.9)",
					titleColor: "#fff",
					bodyColor: "#cbd5e1",
					borderColor: "#334155",
					borderWidth: 1,
				},
			},
			scales: {
				y: {
					beginAtZero: true,
					max: 100,
					grid: { color: "rgba(71, 85, 105, 0.2)" },
					ticks: { color: "#9ca3af" },
				},
				x: {
					grid: { display: false },
					ticks: { color: "#9ca3af", maxTicksLimit: 12 },
				},
			},
		},
	});
}

// --- Tab & Settings Logic ---

function switchTab(tabName) {
	const views = ["dashboard", "settings", "applogs"];
	views.forEach((view) => {
		const isTarget = view === tabName;
		document
			.getElementById(`${view}-view`)
			.classList.toggle("hidden", !isTarget);
		const tab = document.getElementById(`tab-${view}`);
		if (isTarget) {
			tab.className =
				"px-4 py-2 rounded-lg bg-gray-800 text-cyan-400 font-medium transition";
		} else {
			tab.className =
				"px-4 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800/50 font-medium transition";
		}
	});
	if (tabName === "settings") loadConfig();
	if (tabName === "applogs") loadAppLogs();
}

let configMode = "visual";

function switchConfigTab(tab) {
	configMode = tab;
	const isVisual = tab === "visual";
	document
		.getElementById("config-visual-view")
		.classList.toggle("hidden", !isVisual);
	document
		.getElementById("config-yaml-view")
		.classList.toggle("hidden", isVisual);

	const vTab = document.getElementById("tab-visual");
	const yTab = document.getElementById("tab-yaml");

	if (isVisual) {
		vTab.className =
			"px-4 py-1.5 text-sm font-bold rounded-md bg-gray-700 text-white shadow transition-all";
		yTab.className =
			"px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-white transition-all";
		loadConfig(); // Refresh visual from server
	} else {
		yTab.className =
			"px-4 py-1.5 text-sm font-bold rounded-md bg-gray-700 text-white shadow transition-all";
		vTab.className =
			"px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-white transition-all";
		loadConfigYaml(); // Refresh yaml from server
	}
}

async function loadConfig() {
	if (configMode === "yaml") return loadConfigYaml();

	try {
		const res = await apiFetch("/api/config/json");
		const data = await res.json();
		if (res.ok) {
			// General
			document.getElementById("f-schedule").value =
				data.general?.monitor_interval_minutes || 360;
			document.getElementById("f-cache").value =
				data.general?.update_check_cache_hours || 6;
			document.getElementById("f-lock").value =
				data.general?.lock_timeout_seconds || 30;
			document.getElementById("f-log-lines").value =
				data.general?.log_lines_to_check || 40;

			// Thresholds
			document.getElementById("f-t-cpu").value =
				data.thresholds?.cpu_warning || 80;
			document.getElementById("f-t-mem").value =
				data.thresholds?.memory_warning || 80;
			document.getElementById("f-t-disk").value =
				data.thresholds?.disk_space || 80;
			document.getElementById("f-t-net").value =
				data.thresholds?.network_error || 10;

			// Auto Update
			document.getElementById("f-au-enabled").checked =
				String(data.auto_update?.enabled).toLowerCase() === "true";
			document.getElementById("f-au-tags").value = (
				data.auto_update?.tags || []
			).join(", ");
			document.getElementById("f-au-include").value = (
				data.auto_update?.include || []
			).join(", ");
			document.getElementById("f-au-exclude").value = (
				data.auto_update?.exclude || []
			).join(", ");

			// Notifications
			document.getElementById("f-notify-channel").value =
				data.notifications?.channel || "none";
			document.getElementById("f-notify-on").value =
				data.notifications?.notify_on || "Updates,Logs";
			document.getElementById("f-discord").value =
				data.notifications?.discord?.webhook_url || "";
			document.getElementById("f-generic").value =
				data.notifications?.generic?.webhook_url || "";
			document.getElementById("f-hc-url").value =
				data.general?.healthchecks_job_url || "";
			document.getElementById("f-disable-token").checked =
				data.auth?.disable_token_auth === true;
		} else {
			showToast("Error loading config JSON", "error");
		}
	} catch (_e) {
		showToast("Failed to load config", "error");
	}
}

async function loadConfigYaml() {
	try {
		const res = await apiFetch("/api/config");
		const text = await res.text();
		if (res.ok) {
			document.getElementById("config-editor").value = text;
		} else {
			document.getElementById("config-editor").value = "# Error loading config";
		}
	} catch (_e) {
		showToast("Failed to load YAML config", "error");
	}
}

async function saveConfig() {
	const statusText = document.getElementById("config-save-status");
	statusText.innerText = "⏳ Saving...";
	statusText.className = "text-sm font-medium text-yellow-400";

	try {
		let res;
		if (configMode === "visual") {
			const resJson = await apiFetch("/api/config/json");
			const baseData = await resJson.json();

			baseData.general = baseData.general || {};
			baseData.general.monitor_interval_minutes =
				parseInt(document.getElementById("f-schedule").value, 10) || 360;
			baseData.general.update_check_cache_hours =
				parseInt(document.getElementById("f-cache").value, 10) || 6;
			baseData.general.lock_timeout_seconds =
				parseInt(document.getElementById("f-lock").value, 10) || 30;
			baseData.general.log_lines_to_check =
				parseInt(document.getElementById("f-log-lines").value, 10) || 40;
			baseData.general.healthchecks_job_url = document
				.getElementById("f-hc-url")
				.value.trim();

			baseData.thresholds = baseData.thresholds || {};
			baseData.thresholds.cpu_warning =
				parseInt(document.getElementById("f-t-cpu").value, 10) || 80;
			baseData.thresholds.memory_warning =
				parseInt(document.getElementById("f-t-mem").value, 10) || 80;
			baseData.thresholds.disk_space =
				parseInt(document.getElementById("f-t-disk").value, 10) || 80;
			baseData.thresholds.network_error =
				parseInt(document.getElementById("f-t-net").value, 10) || 10;

			baseData.auto_update = baseData.auto_update || {};
			baseData.auto_update.enabled =
				document.getElementById("f-au-enabled").checked;
			baseData.auto_update.tags = document
				.getElementById("f-au-tags")
				.value.split(",")
				.map((s) => s.trim())
				.filter(Boolean);
			baseData.auto_update.include = document
				.getElementById("f-au-include")
				.value.split(",")
				.map((s) => s.trim())
				.filter(Boolean);
			baseData.auto_update.exclude = document
				.getElementById("f-au-exclude")
				.value.split(",")
				.map((s) => s.trim())
				.filter(Boolean);

			baseData.auth = baseData.auth || {};
			baseData.auth.disable_token_auth =
				document.getElementById("f-disable-token").checked;

			baseData.notifications = baseData.notifications || {};
			baseData.notifications.channel =
				document.getElementById("f-notify-channel").value;
			baseData.notifications.notify_on =
				document.getElementById("f-notify-on").value.trim() || "Updates,Logs";

			baseData.notifications.discord = baseData.notifications.discord || {};
			baseData.notifications.discord.webhook_url = document
				.getElementById("f-discord")
				.value.trim();

			baseData.notifications.generic = baseData.notifications.generic || {};
			baseData.notifications.generic.webhook_url = document
				.getElementById("f-generic")
				.value.trim();

			res = await apiFetch("/api/config/json", {
				method: "PUT",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(baseData),
			});
		} else {
			const yamlText = document.getElementById("config-editor").value;
			res = await apiFetch("/api/config", {
				method: "PUT",
				headers: { "Content-Type": "text/plain" },
				body: yamlText,
			});
		}

		if (res.ok) {
			statusText.innerText = "";
			showToast("Configuration saved successfully!", "success");
		} else {
			const data = await res.json();
			statusText.innerText = "";
			showToast(`Invalid configuration format: ${data.detail || ""}`, "error");
		}
	} catch {
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
	} catch (_e) {
		logBox.textContent = "Network error loading logs.";
	}
}

async function systemPrune() {
	const confirmed = await customConfirm(
		"System Prune",
		"⚠️ WARNING: This will remove ALL stopped containers, unused networks, and unused images. Are you sure you want to proceed?",
	);
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
	} catch {
		showToast("Network error during prune.", "error");
	}
}

// Bind global functions for HTML inline event handlers
window.login = login;
window.switchTab = switchTab;
window.updateAll = updateAll;
window.triggerRun = triggerRun;
window.logout = logout;
window.switchConfigTab = switchConfigTab;
window.saveConfig = saveConfig;
window.systemPrune = systemPrune;
window.closeLogModal = closeLogModal;
window.closeMetricsModal = closeMetricsModal;
window.viewLogs = viewLogs;
window.viewMetrics = viewMetrics;
window.controlContainer = controlContainer;
window.updateContainer = updateContainer;
window.loginWithPasskey = loginWithPasskey;
window.registerPasskey = registerPasskey;
