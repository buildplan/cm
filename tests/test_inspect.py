import docker

client = docker.from_env()
# Create a dummy container with lots of settings to inspect its HostConfig
try:
    c = client.containers.run(
        "alpine",
        "sleep 100",
        detach=True,
        name="test_inspect",
        sysctls={"net.ipv4.ip_forward": 1},
        security_opt=["no-new-privileges:true"],
        extra_hosts={"host.docker.internal": "172.17.0.1"},
        dns=["8.8.8.8"],
        tmpfs={"/run": ""},
    )
    print(list(c.attrs["HostConfig"].keys()))
    c.remove(force=True)
except Exception as e:
    print(e)
