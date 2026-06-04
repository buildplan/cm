import docker
client = docker.from_env()
for c in client.containers.list():
    tags = c.image.tags
    config_image = c.attrs.get("Config", {}).get("Image")
    print(f"Container: {c.name}, Tags: {tags}, Config Image: {config_image}")
