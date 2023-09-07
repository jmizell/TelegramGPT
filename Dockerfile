FROM python:3.11

RUN mkdir /app
COPY . /app
WORKDIR /app

RUN mkdir data
RUN pip install -r requirements.txt

ENTRYPOINT [ "/usr/local/bin/python", "/app/bot.py" ]