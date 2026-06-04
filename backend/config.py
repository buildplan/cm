from pydantic import BaseModel, Field
from typing import List, Dict


class GeneralConfig(BaseModel):
    monitor_interval_minutes: int = 360
    log_lines_to_check: int = 40
    log_file: str = "/app/data/container-monitor.log"
    update_check_cache_hours: int = 6
    lock_timeout_seconds: int = 30
    healthchecks_job_url: str = ""
    healthchecks_fail_on: str = ""


class LogsConfig(BaseModel):
    error_patterns: List[str] = ["Exception", "SEVERE", "Traceback"]
    log_clean_pattern: str = "^[^ ]+[\\s]+"
    ignore_patterns: Dict[str, List[str]] = {}


class AuthConfig(BaseModel):
    docker_username: str = ""
    docker_password: str = ""
    docker_config_path: str = "~/.docker/config.json"


class ThresholdsConfig(BaseModel):
    cpu_warning: int = 80
    memory_warning: int = 80
    disk_space: int = 80
    network_error: int = 10


class HostSystemConfig(BaseModel):
    disk_check_filesystem: str = "/"


class DiscordConfig(BaseModel):
    webhook_url: str = ""


class GenericConfig(BaseModel):
    webhook_url: str = ""


class NtfyConfig(BaseModel):
    server_url: str = "https://ntfy.sh"
    topic: str = ""
    access_token: str = ""
    priority: int = 3
    icon_url: str = ""
    click_url: str = ""


class NotificationsConfig(BaseModel):
    channel: str = "none"
    notify_on: str = "Updates,Logs"
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    generic: GenericConfig = Field(default_factory=GenericConfig)
    ntfy: NtfyConfig = Field(default_factory=NtfyConfig)


class ExcludeConfig(BaseModel):
    updates: List[str] = []


class ContainersConfig(BaseModel):
    monitor_defaults: List[str] = []
    release_urls: Dict[str, str] = {}
    update_strategies: Dict[str, str] = {}
    exclude: ExcludeConfig = Field(default_factory=ExcludeConfig)


class AutoUpdateConfig(BaseModel):
    enabled: bool = False
    tags: List[str] = []
    include: List[str] = []
    exclude: List[str] = []


class AppConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    host_system: HostSystemConfig = Field(default_factory=HostSystemConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    containers: ContainersConfig = Field(default_factory=ContainersConfig)
    auto_update: AutoUpdateConfig = Field(default_factory=AutoUpdateConfig)
