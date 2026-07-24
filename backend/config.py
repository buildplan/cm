from pydantic import BaseModel, Field


class GeneralConfig(BaseModel):
    monitor_interval_minutes: int = 360
    log_lines_to_check: int = 40
    log_file: str = "/app/data/container-monitor.log"
    update_check_cache_hours: int = 6
    lock_timeout_seconds: int = 30
    healthchecks_job_url: str = ""
    healthchecks_fail_on: str = ""


class LogsConfig(BaseModel):
    error_patterns: list[str] = ["Exception", "SEVERE", "Traceback"]
    log_clean_pattern: str = "^[^ ]+[\\s]+"
    ignore_patterns: dict[str, list[str]] = {}


class AuthConfig(BaseModel):
    docker_username: str = ""
    docker_password: str = ""
    docker_config_path: str = "~/.docker/config.json"
    disable_token_auth: bool = False


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
    updates: list[str] = []


class ContainersConfig(BaseModel):
    monitor_defaults: list[str] = []
    release_urls: dict[str, str] = {}
    update_strategies: dict[str, str] = {}
    exclude: ExcludeConfig = Field(default_factory=ExcludeConfig)


class AutoUpdateConfig(BaseModel):
    enabled: bool = False
    tags: list[str] = []
    include: list[str] = []
    exclude: list[str] = []


class AppConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    host_system: HostSystemConfig = Field(default_factory=HostSystemConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    containers: ContainersConfig = Field(default_factory=ContainersConfig)
    auto_update: AutoUpdateConfig = Field(default_factory=AutoUpdateConfig)
