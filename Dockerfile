# Alpine for smaller size
FROM python:3.9-alpine

# Create a system account hubibot.hubibot
RUN addgroup -S hubibot && adduser -S hubibot -G hubibot
# Non-alpine equivalent of above:
#RUN groupadd -r hubibot && useradd -r -m -g hubibot hubibot

USER hubibot

WORKDIR /app

COPY requirements.txt     /app
COPY main.py              /app
COPY template.config.yaml /app

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r ./requirements.txt --no-warn-script-location 

ENTRYPOINT python main.py
