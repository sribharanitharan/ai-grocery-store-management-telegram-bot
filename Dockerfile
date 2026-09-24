FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output for real-time logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for fonts and graphics rendering (ReportLab & Matplotlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source code
COPY . .

# Ensure output directory exists for generated invoices and PPTX decks
RUN mkdir -p output

CMD ["python", "main.py"]
