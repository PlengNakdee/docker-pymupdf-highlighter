FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
  fastapi \
  uvicorn \
  python-multipart \
  PyMuPDF==1.26.5

COPY app.py .

EXPOSE 8001

CMD ["python", "app.py"]