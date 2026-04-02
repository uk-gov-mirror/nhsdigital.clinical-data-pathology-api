# This file is for you! Edit it to implement your own hooks (make targets) into
# the project as automated steps to be executed on locally and in the CD pipeline.

include scripts/init.mk

# Within the build container the `doas` command is required when running docker commands as we're running as a non-root user.
ifeq (${IN_BUILD_CONTAINER}, true)
docker := doas docker
else
docker := docker
endif

dockerNetwork := pathology-local

# ==============================================================================

# Example CI/CD targets are: dependencies, build, publish, deploy, clean, etc.

.PHONY: dependencies
.ONESHELL:
dependencies: # Install dependencies needed to build and test the project @Pipeline
	if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		eval "$$(pyenv init -)"; \
		pyenv activate pathology; \
	fi

	cd pathology-api && poetry sync
	cd ../

	if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		pyenv deactivate pathology; \
	fi

	if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		pyenv activate pathology-mocks; \
	fi

	cd mocks && poetry sync
	cd ../

	if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		pyenv deactivate pathology-mocks; \
	fi

.PHONY: build-pathology
.ONESHELL:
build-pathology:
	@if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		eval "$$(pyenv init -)"; \
		pyenv activate pathology; \
	fi

	@cd pathology-api
	@echo "Starting build for pathology API..."
	@echo "Running type checks..."
	@rm -rf target && rm -rf dist
	@poetry run mypy --no-namespace-packages .
	@echo "Packaging dependencies..."
	@poetry build --format=wheel
	VERSION=$$(poetry version -s)
	@pip install "dist/pathology_api-$$VERSION-py3-none-any.whl" --target "./target/pathology-api" --platform manylinux2014_x86_64 --only-binary=:all:
	# Copy lambda_handler file separately as it is not included within the package.
	@cp lambda_handler.py ./target/pathology-api/
	@cd ./target/pathology-api
	@zip -r "../artifact.zip" .

	@if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		pyenv deactivate pathology; \
	fi

.PHONY: build-mocks
.ONESHELL:
build-mocks:
	@if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		eval "$$(pyenv init -)"; \
		pyenv activate pathology-mocks; \
	fi

	@cd mocks
	@echo "Starting build for mocks..."
	@echo "Running type checks..."
	@rm -rf target && rm -rf dist
	@poetry run mypy --no-namespace-packages .
	@echo "Packaging dependencies..."
	@poetry build --format=wheel
	VERSION=$$(poetry version -s)
	@pip install "dist/pathology_api_mocks-$$VERSION-py3-none-any.whl" --target "./target/mocks" --platform manylinux2014_x86_64 --only-binary=:all:
	# Copy lambda_handler file separately as it is not included within the package.
	@cp lambda_handler.py ./target/mocks/
	@cd ./target/mocks
	@zip -r "../artifact.zip" .

	@if [[ "$${IN_BUILD_CONTAINER}" == "true" ]]; then \
		pyenv deactivate pathology-mocks; \
	fi

.PHONY: build
build: clean-artifacts dependencies build-pathology build-mocks
	@echo "Built artifacts for both pathology and mocks"


.PHONY: build-images
build-images: build # Build the project artefact @Pipeline
	@mkdir -p infrastructure/images/pathology-api/resources/build
	@cp -r pathology-api/target/pathology-api infrastructure/images/pathology-api/resources/build

	@mkdir -p infrastructure/images/mocks/resources/build
	@cp -r mocks/target/mocks infrastructure/images/mocks/resources/build

	@echo "Building Docker image using Docker. Utilising python version: ${PYTHON_VERSION} ..."
	@$(docker) buildx build --load --platform=linux/amd64 --provenance=false --build-arg PYTHON_VERSION=${PYTHON_VERSION} -t localhost/pathology-api-image infrastructure/images/pathology-api
	@echo "Docker image 'pathology-api-image' built successfully!"

	@echo "Building api gateway image using Docker. Utilising python version: ${PYTHON_VERSION} ..."
	@$(docker) buildx build --load --build-arg PYTHON_VERSION=${PYTHON_VERSION} -t localhost/api-gateway-mock-image infrastructure/images/api-gateway-mock
	@echo "Docker image 'api-gateway-mock-image' built successfully!"

	@echo "Building mocks Docker image using Docker. Utilising python version: ${PYTHON_VERSION} ..."
	@$(docker) buildx build --load --platform=linux/amd64 --provenance=false --build-arg PYTHON_VERSION=${PYTHON_VERSION} -t localhost/mocks-image infrastructure/images/mocks
	@echo "Docker image 'mocks-image' built successfully!"

publish: # Publish the project artefact @Pipeline
	# TODO: Implement the artefact publishing step

deploy: clean-docker build-images # Deploy the project artefact to the target environment @Pipeline
	$(docker) network create $(dockerNetwork) || echo "Docker network '$(dockerNetwork)' already exists."
	$(docker) run --platform linux/amd64 --name pathology-api -p 5001:8080 --network $(dockerNetwork) -d localhost/pathology-api-image
	$(docker) run --platform linux/amd64 --name mocks -p 5003:8080 --network $(dockerNetwork) -d localhost/mocks-image
	$(docker) run --name pathology-api-gateway -p 5002:5000 -e TARGET_CONTAINER='PATHOLOGY_API' -e TARGET_URL='http://pathology-api:8080' --network $(dockerNetwork) -d localhost/api-gateway-mock-image
	$(docker) run --name mocks-api-gateway -p 5005:5000 -e TARGET_CONTAINER='MOCKS' -e TARGET_URL='http://mocks:8080' --network $(dockerNetwork) -d localhost/api-gateway-mock-image

clean-artifacts:
	@echo "Removing build artefacts..."
	@rm -rf infrastructure/images/pathology-api/resources/build/
	@rm -rf pathology-api/target && rm -rf pathology-api/dist
	@rm -rf infrastructure/images/mocks/resources/build/
	@rm -rf mocks/target && rm -rf mocks/dist

clean-docker: stop
	@echo "Removing pathology API container..."
	@$(docker) rm pathology-api || echo "No pathology API container currently exists."

	@echo "Removing pathology-api api-gateway container..."
	@$(docker) rm pathology-api-gateway || echo "No pathology-api-gateway container currently exists."

	@echo "Removing mocks container..."
	@$(docker) rm mocks || echo "No mocks container currently exists."

	@echo "Removing mocks api-gateway container..."
	@$(docker) rm mocks-api-gateway || echo "No mocks-api-gateway container currently exists."

clean:: clean-artifacts clean-docker  # Clean-up project resources (main) @Operations

.PHONY: stop
stop:
	@echo "Stopping pathology API container..."
	@$(docker) stop pathology-api || echo "No pathology API container currently running."

	@echo "Stopping pathology-api-gateway container..."
	@$(docker) stop pathology-api-gateway || echo "No pathology-api-gateway container currently running."

	@echo "Stopping mocks container..."
	@$(docker) stop mocks || echo "No mocks container currently running."

	@echo "Stopping mocks-api-gateway container..."
	@$(docker) stop mocks-api-gateway || echo "No mocks-api-gateway container currently running."

config:: # Configure development environment (main) @Configuration
	# Configure poetry to trust dev certificate if specified
	@if [[ -n "$${DEV_CERTS_INCLUDED}" ]]; then \
		echo "Configuring poetry to trust the dev certificate..."  ; \
		poetry config certificates.PyPI.cert /etc/ssl/cert.pem ; \
	fi
	make _install-dependencies

# ==============================================================================

${VERBOSE}.SILENT: \
	build \
	clean \
	config \
	dependencies \
	deploy \
