# Variables
IMAGE_NAME = summarizer-app
CONTAINER_NAME = my-running-app
PORT = 7860

.PHONY: build run stop clean test

# Build the docker container safely
build:
	docker build --no-cache -t summarizer-app .

# Run the container and inject your SCA secret into the container's HF_TOKEN variable
run:
	-docker rm -f $(CONTAINER_NAME)
	docker run -d -p $(PORT):$(PORT) --name $(CONTAINER_NAME) -e HF_TOKEN="$$(echo $$SCA)" $(IMAGE_NAME)

# Stop and remove the container
stop:
	-docker stop $(CONTAINER_NAME)
	-docker rm $(CONTAINER_NAME)

# Execute the test suite inside the running container
test:
	docker exec -it $(CONTAINER_NAME) python -m unittest test.py