# Telegram Chatbot with OpenAI GPT and SQLite

## Overview

This project is a Telegram chatbot built using Python. It utilizes the OpenAI GPT model for generating conversational responses and SQLite for storing chat history. The chatbot is designed to provide concise and helpful answers.

## Features

- **Token Management**: Efficiently manages the token count for API requests to OpenAI.
- **User Authorization**: Only allows authorized users to interact with the bot.
- **Chat History**: Stores the chat history in a SQLite database.
- **Environment Variables**: Configurable settings using environment variables.

## Prerequisites

- Python 3.x
- SQLite
- OpenAI Python package
- Telegram API
- Tiktoken Python package

## Installation

1. Clone this repository.
2. Install the required Python packages.

    ```bash
    pip install -r requirements.txt
    ```

3. Set up your environment variables. You can either export them in your shell or create a `.env` file.

    ```bash
    export TELEGRAM_BOT_KEY=your_telegram_bot_key
    export OPENAI_API_KEY=your_openai_key
    export MAX_TOKENS=16000
    export MODEL_NAME=gpt-3.5-turbo-16k
    export ALLOWED_USERS='[9999999, 1111111]'
    ```

    Or in a `.env` file:

    ```
    TELEGRAM_BOT_KEY=your_telegram_bot_key
    OPENAI_API_KEY=your_openai_key
    MAX_TOKENS=16000
    MODEL_NAME=gpt-3.5-turbo-16k
    ALLOWED_USERS=[user_id1, user_id2]
    ```

## Usage

Run the main Python script to start the bot.

```bash
python bot.py
```

### Customizing the System Message

You can customize the system message that guides the chatbot's behavior by editing the `system.txt` file.

## Docker Deployment

### Configuration

Before building and running the Docker container, make sure to create a `config.env` file in the same directory as your Dockerfile. Add your Telegram bot API key and OpenAI API key to this file:

```env
TELEGRAM_BOT_KEY=your_telegram_bot_key_here
OPENAI_API_KEY=your_openai_api_key_here
# Add other environment variables as needed
```

### Building the Docker Image

To build the Docker image, navigate to the directory containing the Dockerfile and run:

```bash
docker build -t telegramgpt:latest .
```

This will build a Docker image and tag it as `telegramgpt:latest`.


### Running the Docker Container

To run the Docker container in detached mode, you can use the following command:

```bash
docker run -d --name telegramgpt --restart=always --env-file config.env -v ${PWD}/data:/app/data telegramgpt:latest
```

This command does the following:

- `-d` runs the container in detached mode, in the background.
- `--name telegramgpt` names the container "telegramgpt".
- `--restart=always` ensures the container restarts automatically if it stops.
- `--env-file config.env` specifies a file from which to read environment variables, including your Telegram bot and OpenAI API keys.
- `-v ${PWD}/data:/app/data` mounts the `data` directory from your current location to `/app/data` in the container, allowing the SQLite database to be stored persistently.

## Environment Variables

- `TELEGRAM_BOT_KEY`: Your Telegram bot API key.
- `OPENAI_API_KEY`: Your OpenAI API key. This is required for making API requests to OpenAI.
- `MAX_TOKENS`: The maximum number of tokens for API requests (default is 16000).
- `MODEL_NAME`: The OpenAI GPT model name (default is `gpt-3.5-turbo-16k`).
- `ALLOWED_USERS`: A JSON array of telegram user IDs that are allowed to interact with the bot (default is an empty array).

## Contributing

Feel free to submit pull requests or issues to improve the bot.
