FROM python:3.11-slim

# Set folder kerja di dalam server
WORKDIR /app

# Install library sistem yang dibutuhkan (termasuk untuk Pillow)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements dan install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy seluruh sisa kode project
COPY . .

# Buat folder data agar aplikasi tidak error saat menyimpan session
RUN mkdir -p data

# Render akan menyuntikkan port otomatis ke environment variable $PORT
# Kita gunakan perintah bawaan dari app.py kamu
CMD ["python", "app.py"]