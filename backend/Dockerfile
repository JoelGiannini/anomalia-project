FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    openssh-client \
    sshpass \
    && rm -rf /var/lib/apt/lists/*

# Configuración SSH para no solicitar confirmación al conectarse a servidores
RUN mkdir -p /root/.ssh && \
    printf '%s\n' \
    'Host *' \
    '    StrictHostKeyChecking no' \
    '    UserKnownHostsFile /dev/null' \
    > /root/.ssh/config && \
    chmod 600 /root/.ssh/config

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
