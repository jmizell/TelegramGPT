#!/bin/bash

echo "build new image"
docker build -t telegramgpt:latest .

echo "remove old container"
docker kill telegramgpt
docker rm telegramgpt

echo "start new container"
docker run -d --name telegramgpt --restart=always --env-file config.env -v ${PWD}/data:/app/data telegramgpt:latest
