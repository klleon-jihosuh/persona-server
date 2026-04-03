FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 데이터 디렉토리 생성
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["python", "main.py"]
