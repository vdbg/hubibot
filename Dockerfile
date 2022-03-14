FROM python:3.7

# Create a system account hubibot.hubibot
RUN groupadd -r hubibot && useradd -r -m -g hubibot hubibot

USER hubibot

WORKDIR /app

COPY requirements.txt     /app
COPY main.py              /app
COPY template.config.yaml /app


RUN pip3 install -r ./requirements.txt --no-warn-script-location

ENTRYPOINT python3 main.py
