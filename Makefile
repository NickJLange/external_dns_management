-include .env

BATCH_HOST ?= BatchNode
DEPLOY_PATH ?= /data/infrastructure/dns_management

.PHONY: build deploy

build:
	@echo "Building dns-sync image..."
	podman build -t localhost/dns-sync:latest -f Containerfile .

deploy:
	@echo "Deploying dns-sync to $(BATCH_HOST):$(DEPLOY_PATH)..."
	ssh $(BATCH_HOST) 'test -d $(DEPLOY_PATH) || git clone --recurse-submodules git@github.com:NickJLange/external_dns_management.git $(DEPLOY_PATH)'
	ssh $(BATCH_HOST) 'cd $(DEPLOY_PATH) && podman build -t localhost/dns-sync:latest -f Containerfile .'
	ssh $(BATCH_HOST) 'mkdir -p ~/.config/containers/systemd && cp $(DEPLOY_PATH)/systemd/dns-sync.container $(DEPLOY_PATH)/systemd/dns-sync.timer ~/.config/containers/systemd/'
	ssh $(BATCH_HOST) 'systemctl --user daemon-reload && systemctl --user enable --now dns-sync.timer && loginctl enable-linger $$(whoami)'
	@echo "Deploy complete. etc/porkbun_secrets.env and gh auth login are one-time manual steps."
