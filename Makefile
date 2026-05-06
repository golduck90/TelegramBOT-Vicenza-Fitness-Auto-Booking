.PHONY: build up down logs shell clean help restart

build:  ## Builda l'immagine Docker
	docker compose build

up:  ## Avvia il bot in background
	docker compose up -d

down:  ## Ferma e rimuove il container
	docker compose down

logs:  ## Mostra i log in tempo reale
	docker compose logs -f --tail=100

shell:  ## Apre una shell nel container
	docker compose exec bot-palestra bash

restart:  ## Ricostruisce e riavvia il bot
	docker compose down
	docker compose build
	docker compose up -d

clean:  ## Pulisce container, volumi e immagini non usati
	docker system prune -af --volumes

help:  ## Mostra questo help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
