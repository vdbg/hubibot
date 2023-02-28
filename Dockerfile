FROM python:3.11-alpine

RUN addgroup -S hubibot && adduser -S hubibot -G hubibot

USER hubibot

WORKDIR /app

# Prevents Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED 1
# Install location of upgraded pip
ENV PATH /home/hubibot/.local/bin:$PATH

COPY requirements.txt     /app/

RUN pip install --no-cache-dir --disable-pip-version-check --upgrade pip
RUN pip install --no-cache-dir -r ./requirements.txt

COPY *.py                 /app/
COPY template.config.yaml /app/

ENTRYPOINT python main.py
