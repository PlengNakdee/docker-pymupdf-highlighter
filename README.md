# docker-pymupdf-highlighter

## Run Docker

```bash
docker build -t highlighter .
docker run -p 8000:8000 -v $(pwd)/output:/app/output highlighter
```

## In Terminal Run Local Tunnel

```bash
cloudflared tunnel --url http://localhost:8000
```

## Use URL Inside HTTP Request Node in n8n

Example: `https://little-tools-thank.loca.lt/process`

## If Use cURL

```bash
curl -X POST "http://localhost:8000/process" \
-F "file=@file1.pdf"
```
