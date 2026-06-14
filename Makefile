.PHONY: help build run-checkpoint run-forticlient

help:
	@echo "Usage:"
	@echo "  make build            Build the enterprise-jailbreak Docker image"
	@echo "  make run-checkpoint   Run with CheckPoint VPN (requires .env + secrets/checkpoint_vpn_password.txt)"
	@echo "  make run-forticlient  Run with FortiClient VPN (requires .env + secrets/forti_vpn_password.txt)"

build:
	docker build --platform linux/arm64 -t enterprise-jailbreak .

run-checkpoint:
	docker compose --profile checkpoint up

run-forticlient:
	docker compose --profile forticlient up
