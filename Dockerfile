FROM python:3.11-slim

WORKDIR /app

# Install library sistem
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy SELURUH file project
COPY . .

# Buat folder data
RUN mkdir -p data

# KUNCI UTAMA: Daftarkan /app dan /app/tools langsung di sys.path Python saat container menyala
ENV PYTHONPATH="/app:/app/tools"

# Jalankan aplikasi
CMD ["python", "app.py"]