FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATABASE_PATH=/data/finance.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
# --preload: สร้าง/อัปเกรดฐานข้อมูลครั้งเดียวก่อนแตก worker
CMD ["sh", "-c", "gunicorn --preload -w 2 -b 0.0.0.0:${PORT:-8000} --access-logfile - app:app"]
