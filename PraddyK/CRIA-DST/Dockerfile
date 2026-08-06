FROM python:3.11-slim

# No system/GDAL deps needed: the runtime uses only wheel-installable packages
# (dash, plotly, pandas, numpy, scipy, matplotlib, pyarrow). This keeps the
# HuggingFace build fast and avoids the previous "Job timeout" build error.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HuggingFace Spaces runs as non-root user 1000
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER appuser

EXPOSE 7860

CMD ["gunicorn", "app:server", "--bind", "0.0.0.0:7860", "--workers", "2", "--timeout", "120"]
