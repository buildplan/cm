import docker
import json
import os
import re
import yaml
import time
import httpx
from datetime import datetime
from pathlib import Path
from backend.state import StateManager

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
CONFIG_F = DATA_DIR / "config.yml"
STATE_DB = DATA_DIR / "monitor_state.db"
LOG_F = DATA_DIR / "container-monitor.log"

import subprocess
def log_event(msg: str, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} [{level}] {msg}\n"
    try:
        with open(LOG_F, "a") as f:
            f.write(log_line)
    except Exception:
        pass
    print(log_line.strip())

def get_container_logs(container_name: str, filter_str: str = "") -> str:
    try:
        client = docker.from_env()
        container = client.containers.get(container_name)
        lines = 20
        if CONFIG_F.exists():
            try:
                with open(CONFIG_F, "r") as f:
                    cfg = yaml.safe_load(f) or {}
                    lines = int(cfg.get("general", {}).get("log_lines_to_check", 20))
            except: pass
        logs = container.logs(tail=lines).decode("utf-8", errors="replace")
        if filter_str:
            pattern = re.compile(filter_str, re.IGNORECASE)
            logs = "\n".join([line for line in logs.splitlines() if pattern.search(line)])
        return logs
    except Exception as e:
        return f"Error fetching logs: {e}"

def get_registry_tags(image_name):
    if ":" in image_name:
        image_name = image_name.split(":")[0]
    registry = "registry-1.docker.io"
    repo = image_name
    if "/" in image_name:
        parts = image_name.split("/", 1)
        if "." in parts[0] or ":" in parts[0] or parts[0] == "localhost":
            registry = parts[0]
            repo = parts[1]
    else:
        repo = f"library/{image_name}"
    url = f"https://{registry}/v2/"
    try:
        r = httpx.get(url, timeout=10)
        token = ""
        if r.status_code == 401:
            auth = r.headers.get("Www-Authenticate", "")
            if auth.lower().startswith("bearer"):
                realm_m = re.search(r'realm="([^"]+)"', auth)
                service_m = re.search(r'service="([^"]+)"', auth)
                if realm_m:
                    realm = realm_m.group(1)
                    service = service_m.group(1) if service_m else ""
                    auth_url = f"{realm}?service={service}&scope=repository:{repo}:pull"
                    tr = httpx.get(auth_url, timeout=10)
                    if tr.status_code == 200:
                        token = tr.json().get("token") or tr.json().get("access_token")
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        tags_url = f"https://{registry}/v2/{repo}/tags/list"
        resp = httpx.get(tags_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("tags", [])
    except Exception:
        pass
    return []

def parse_version(tag):
    m = re.search(r'^v?(\d+)\.(\d+)(?:\.(\d+))?', tag)
    if m:
        return [int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)]
    return [-1, -1, -1]

def get_latest_tag(tags, current_tag, strategy):
    valid_tags = []
    if strategy == "major-lock":
        m = re.search(r'^v?(\d+)', current_tag)
        if m:
            major = m.group(1)
            pattern = re.compile(rf'^v?{major}\.\d+(?:\.\d+)?$')
            valid_tags = [t for t in tags if pattern.match(t)]
    elif strategy == "semver":
        pattern = re.compile(r'^v?\d+\.\d+(?:\.\d+)?$')
        valid_tags = [t for t in tags if pattern.match(t)]

    if not valid_tags:
        return None
    valid_tags.sort(key=parse_version)
    return valid_tags[-1]

class Monitor:
    def __init__(self, force=False, **kwargs):
        self.force = force
        self.config = {}
        if CONFIG_F.exists():
            with open(CONFIG_F, "r") as f:
                self.config = yaml.safe_load(f) or {}
        try:
            self.client = docker.from_env()
        except Exception as e:
            self.client = None
            log_event(f"Docker connection failed: {e}", "ERROR")

        self.state_mgr = StateManager(STATE_DB)
        self.state = self.state_mgr.get_all()

        if "updates" not in self.state: self.state["updates"] = {}
        if "restarts" not in self.state: self.state["restarts"] = {}
        if "logs" not in self.state: self.state["logs"] = {}
        if "container_issues" not in self.state: self.state["container_issues"] = {}

        self.on_update = kwargs.get('on_update')

    def save_state(self):
        try:
            self.state_mgr.update(self.state)
            if self.on_update:
                self.on_update("state_changed", self.state)
        except Exception as e:
            log_event(f"Failed to save state: {e}", "ERROR")

    def run(self):
        log_event("Starting monitor cycle...", "INFO")
        if not self.client:
            log_event("Cannot run monitor cycle: Docker client not initialized.", "ERROR")
            return

        hc_url = self.config.get("general", {}).get("healthchecks_job_url", "")
        hc_fail_on = self.config.get("general", {}).get("healthchecks_fail_on", "")
        if hc_url:
            try: httpx.get(f"{hc_url.rstrip('/')}/start", timeout=5)
            except: pass

        containers = self.client.containers.list(all=True)
        log_event(f"Found {len(containers)} containers to evaluate.", "INFO")
        monitor_defaults = self.config.get("containers", {}).get("monitor_defaults", [])
        exclude_updates = self.config.get("containers", {}).get("exclude", {}).get("updates", [])

        auto_update_cfg = self.config.get("auto_update", {})
        au_enabled = str(auto_update_cfg.get("enabled", "false")).lower() == "true"
        au_tags = auto_update_cfg.get("tags", ["latest", "stable", "main", "master", "nightly"])
        au_include = auto_update_cfg.get("include", [])
        au_exclude = auto_update_cfg.get("exclude", [])

        issues_found = {}
        containers_to_auto_update = []

        for c in containers:
            name = c.name
            if monitor_defaults and name not in monitor_defaults:
                continue

            log_event(f"Evaluating container: {name}", "DEBUG")
            issues = []

            # Status
            if c.status != "running":
                issues.append(f"Status: {c.status}")
            else:
                health = c.attrs.get("State", {}).get("Health", {}).get("Status")
                if health == "unhealthy":
                    issues.append("Status: Unhealthy")

            # Restarts
            current_restarts = c.attrs.get("RestartCount", 0)
            saved_restarts = self.state["restarts"].get(name, 0)
            if current_restarts > saved_restarts:
                issues.append(f"Restarts: {current_restarts} (was {saved_restarts})")
            self.state["restarts"][name] = current_restarts

            # Resources (CPU/Mem)
            stats = None
            try:
                stats = c.stats(stream=False)
                cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
                system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats.get("precpu_stats", {}).get("system_cpu_usage", 0)
                cpu_percent = 0.0
                if system_delta > 0 and cpu_delta > 0:
                    cpu_percent = (cpu_delta / system_delta) * len(stats["cpu_stats"].get("cpu_usage", {}).get("percpu_usage", [1])) * 100.0

                mem_usage = stats["memory_stats"].get("usage", 0)
                mem_limit = stats["memory_stats"].get("limit", 1)
                mem_percent = (mem_usage / mem_limit) * 100.0

                cpu_warn = int(self.config.get("thresholds", {}).get("cpu_warning", 80))
                mem_warn = int(self.config.get("thresholds", {}).get("memory_warning", 80))

                if cpu_percent > cpu_warn:
                    issues.append(f"Resources: CPU high ({cpu_percent:.1f}%)")
                    log_event(f"[{name}] CPU usage high: {cpu_percent:.1f}%", "WARNING")
                if mem_percent > mem_warn:
                    issues.append(f"Resources: Mem high ({mem_percent:.1f}%)")
                    log_event(f"[{name}] Memory usage high: {mem_percent:.1f}%", "WARNING")
            except:
                pass

            # Disk Space
            disk_threshold = int(self.config.get("thresholds", {}).get("disk_space", 80))
            mounts = c.attrs.get("Mounts", [])
            for m in mounts:
                dest = m.get("Destination", "")
                if any(x in dest for x in [".sock", "/proc", "/sys", "/dev", "/host/"]):
                    continue
                try:
                    exit_code, output = c.exec_run(["df", "-P", dest])
                    if exit_code == 0:
                        lines = output.decode("utf-8").strip().splitlines()
                        if len(lines) > 1:
                            parts = lines[1].split()
                            if len(parts) >= 5:
                                usage_str = parts[4].replace("%", "")
                                if usage_str.isdigit() and int(usage_str) > disk_threshold:
                                    issues.append(f"Disk: High usage ({usage_str}%) at {dest}")
                                    log_event(f"[{name}] Disk usage high ({usage_str}%) at {dest}", "WARNING")
                except: pass

            # Network
            if 'stats' in locals() and stats:
                net_threshold = int(self.config.get("thresholds", {}).get("network_error", 10))
                try:
                    networks = stats.get("networks", {})
                    for iface, data in networks.items():
                        errors = data.get("rx_errors", 0) + data.get("tx_errors", 0) + data.get("rx_dropped", 0) + data.get("tx_dropped", 0)
                        if errors > net_threshold:
                            issues.append(f"Network: {errors} errors/drops on {iface}")
                            log_event(f"[{name}] Network issues: {errors} errors/drops on {iface}", "WARNING")
                except: pass

            # Logs
            try:
                lines = int(self.config.get("general", {}).get("log_lines_to_check", 20))
                logs = c.logs(tail=lines).decode("utf-8", errors="ignore")
                error_patterns = self.config.get("logs", {}).get("error_patterns", ["Exception", "SEVERE", "Traceback"])
                ignore_patterns = self.config.get("logs", {}).get("ignore_patterns", {}).get(name, [])

                has_error = False
                for line in logs.splitlines():
                    if any(re.search(ep, line, re.IGNORECASE) for ep in error_patterns):
                        if not any(re.search(ip, line, re.IGNORECASE) for ip in ignore_patterns):
                            has_error = True
                            break
                if has_error:
                    issues.append("Logs: Errors detected")
                    log_event(f"[{name}] Log errors detected.", "WARNING")
            except:
                pass

            # Updates
            try:
                image_tags = c.image.tags
                if image_tags and name not in exclude_updates:
                    image_ref = image_tags[0]
                    cache_key = image_ref.replace("/", "_").replace(":", "_")
                    cached = self.state["updates"].get(cache_key)
                    cache_hours = int(self.config.get("general", {}).get("update_check_cache_hours", 6))

                    if not self.force and cached and (time.time() - cached.get("data", {}).get("timestamp", 0) < cache_hours * 3600):
                        if cached.get("data", {}).get("exit_code") == 100:
                            issues.append(f"Updates: {cached['data']['message']}")
                    else:
                        current_tag = "latest"
                        if ":" in image_ref:
                            current_tag = image_ref.split(":")[-1]

                        strategy = self.config.get("containers", {}).get("update_strategies", {}).get(image_ref, "")
                        if not strategy:
                            strategy = self.config.get("containers", {}).get("update_strategies", {}).get(name, "digest")

                        if strategy in ["semver", "major-lock"]:
                            log_event(f"[{name}] Checking remote tags for {image_ref} (Strategy: {strategy})", "DEBUG")
                            tags = get_registry_tags(image_ref)
                            latest = get_latest_tag(tags, current_tag, strategy)
                            if latest and latest != current_tag and parse_version(latest) > parse_version(current_tag):
                                msg = f"Update available: {latest}"
                                log_event(f"[{name}] UPDATE FOUND: {latest} (Current: {current_tag})", "INFO")
                                self.state["updates"][cache_key] = {
                                    "key": cache_key, "image_ref": image_ref,
                                    "data": {"message": msg, "exit_code": 100, "timestamp": int(time.time())}
                                }
                                issues.append(f"Updates: {msg}")
                                if au_enabled and (current_tag in au_tags):
                                    if (not au_exclude or name not in au_exclude) and (not au_include or name in au_include):
                                        containers_to_auto_update.append(name)
                            else:
                                self.state["updates"][cache_key] = {
                                    "key": cache_key, "image_ref": image_ref,
                                    "data": {"message": "Up to date", "exit_code": 0, "timestamp": int(time.time())}
                                }
                        else:
                            log_event(f"[{name}] Checking remote digest for {image_ref} (Strategy: digest)", "DEBUG")
                            reg_data = self.client.images.get_registry_data(image_ref)
                            local_digest = None
                            repo_digests = c.image.attrs.get("RepoDigests", [])
                            if repo_digests:
                                local_digest = repo_digests[0].split("@")[-1]

                            remote_digest = reg_data.id
                            if local_digest and remote_digest and local_digest != remote_digest:
                                msg = "Update available"
                                log_event(f"[{name}] UPDATE FOUND: New digest available for {image_ref}", "INFO")
                                self.state["updates"][cache_key] = {
                                    "key": cache_key, "image_ref": image_ref,
                                    "data": {"message": msg, "exit_code": 100, "timestamp": int(time.time())}
                                }
                                issues.append(f"Updates: {msg}")
                                if au_enabled and (current_tag in au_tags):
                                    if (not au_exclude or name not in au_exclude) and (not au_include or name in au_include):
                                        containers_to_auto_update.append(name)
                            else:
                                self.state["updates"][cache_key] = {
                                    "key": cache_key, "image_ref": image_ref,
                                    "data": {"message": "Up to date", "exit_code": 0, "timestamp": int(time.time())}
                                }
            except Exception as e:
                pass

            if issues:
                issues_found[name] = " | ".join(issues)
            else:
                if name in issues_found:
                    del issues_found[name]

        self.state["container_issues"] = issues_found
        self.save_state()
        log_event(f"Monitor cycle completed. {len(issues_found)} containers have issues.", "INFO")

        if containers_to_auto_update:
            log_event(f"Auto-update triggered for: {', '.join(containers_to_auto_update)}", "INFO")
            for au_name in containers_to_auto_update:
                try:
                    inspect = subprocess.run(["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', au_name], capture_output=True, text=True)
                    wdir = inspect.stdout.strip()
                    if wdir and Path(wdir).is_dir():
                        subprocess.run(["docker", "compose", "pull"], cwd=wdir, capture_output=True)
                        subprocess.run(["docker", "compose", "up", "-d", "--force-recreate"], cwd=wdir, capture_output=True)
                        log_event(f"Successfully auto-updated {au_name}", "GOOD")
                except Exception as e:
                    log_event(f"Failed to auto-update {au_name}: {e}", "ERROR")

        if hc_url:
            hc_failed = False
            fail_tags = [t.strip().lower() for t in hc_fail_on.split(",")] if hc_fail_on else []
            if fail_tags and issues_found:
                for c_issues in issues_found.values():
                    for issue in c_issues.split(" | "):
                        tag = issue.split(":")[0].lower()
                        if tag in fail_tags:
                            hc_failed = True
                            break
            try:
                if hc_failed:
                    msg = "Issues detected:\n" + "\n".join([f"{k}: {v}" for k, v in issues_found.items()])
                    httpx.post(f"{hc_url.rstrip('/')}/fail", data=msg, timeout=5)
                else:
                    httpx.post(f"{hc_url.rstrip('/')}", data="OK", timeout=5)
            except: pass

        if issues_found:
            self.send_notifications(issues_found)

    def send_notifications(self, issues):
        channel = self.config.get("notifications", {}).get("channel", "none")
        if channel == "none": return

        msg = "Container Issues Detected:\n"
        for name, issue in issues.items():
            msg += f"- {name}: {issue}\n"

        title = "Docker Monitor Alert"

        if channel == "discord":
            url = self.config.get("notifications", {}).get("discord", {}).get("webhook_url")
            if url and "your_discord" not in url:
                try: httpx.post(url, json={"username": "Docker Monitor", "embeds": [{"title": title, "description": msg, "color": 15158332}]})
                except: pass
        elif channel == "ntfy":
            url = self.config.get("notifications", {}).get("ntfy", {}).get("server_url")
            topic = self.config.get("notifications", {}).get("ntfy", {}).get("topic")
            token = self.config.get("notifications", {}).get("ntfy", {}).get("access_token")
            if url and topic and "your_ntfy" not in topic:
                headers = {"Title": title}
                if token: headers["Authorization"] = f"Bearer {token}"
                try: httpx.post(f"{url}/{topic}", headers=headers, content=msg)
                except: pass
        elif channel == "generic":
            url = self.config.get("notifications", {}).get("generic", {}).get("webhook_url")
            if url:
                try: httpx.post(url, json={"text": f"{title}: {msg}"})
                except: pass
