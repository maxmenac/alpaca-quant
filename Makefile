.PHONY: test test-python test-go lint tree

PYTHON ?= python3

test: test-python test-go

test-python:
	$(PYTHON) -m pytest python/tests

test-go:
	cd go && gofmt -w . && go test ./...

lint:
	ruff check python && cd go && go vet ./...

tree:
	@if command -v tree >/dev/null 2>&1; then \
		tree -a -I '.git'; \
	else \
		find . -not -path '*/.*'; \
	fi
