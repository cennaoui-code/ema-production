# EMA Production Voice Agent
# Root-level Dockerfile for Render deployment
# Builds from apps/voice-agent context

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for layer caching)
COPY apps/voice-agent/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY apps/voice-agent/src/ ./src/
COPY apps/voice-agent/prompts/ ./prompts/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the agent
CMD ["python", "src/agent.py", "start"]
