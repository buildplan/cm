import docker

client = docker.from_env()
print(f"Docker ping: {client.ping()}")
