import docker
import os

client = docker.from_env()
print(f"Docker ping: {client.ping()}")
