IMAGE ?= superagi-chat-backend
RUNPOD_WORKER_IMAGE ?= superagi-runpod-worker
CONTAINER_PORT ?= 7860
HOST_PORT ?= 7860

.PHONY: docker-build docker-build-model docker-run docker-test runpod-worker-build runpod-worker-test

docker-build:
	docker build -t $(IMAGE) .

docker-build-model:
	docker build --build-arg INSTALL_SUPERAGI_DEPS=true -t $(IMAGE) .

docker-run:
	docker run --rm -it \
		-p $(HOST_PORT):$(CONTAINER_PORT) \
		-e PORT=$(CONTAINER_PORT) \
		-e SUPERAGI_HOST=0.0.0.0 \
		-e SUPERAGI_CHAT_DB=/data/chat.sqlite3 \
		-v "$$(pwd)/python_backend/data:/data" \
		$(IMAGE)

docker-test:
	docker run --rm \
		-p 7860:7860 \
		-e PORT=7860 \
		-e SUPERAGI_HOST=0.0.0.0 \
		$(IMAGE) \
		python -m unittest discover -s python_backend/tests

runpod-worker-build:
	docker build -f runpod_worker/Dockerfile -t $(RUNPOD_WORKER_IMAGE) .

runpod-worker-test:
	PYTHONPATH=. python3 -m unittest discover -s runpod_worker/tests
