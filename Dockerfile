# Alpine for smaller size
FROM python:3.9-alpine

# Create a system account hubibot.hubibot
RUN addgroup -S hubibot && adduser -S hubibot -G hubibot
# Non-alpine equivalent of above:
#RUN groupadd -r hubibot && useradd -r -m -g hubibot hubibot

USER hubibot

WORKDIR /app

# set environment variables
# PYTHONDONTWRITEBYTECODE: Prevents Python from writing pyc files to disc
# PYTHONUNBUFFERED: Prevents Python from buffering stdout and stderr
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY requirements.txt     /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ./requirements.txt --no-warn-script-location 

COPY main.py              /app
COPY template.config.yaml /app

ENTRYPOINT python main.py
