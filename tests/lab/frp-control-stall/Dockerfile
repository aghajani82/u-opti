FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends nginx openssl && rm -rf /var/lib/apt/lists/*
# Run only with --network none, no published ports, and read-only lab mounts.
