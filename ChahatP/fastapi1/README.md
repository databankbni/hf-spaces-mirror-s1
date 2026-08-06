---
title: FastAPI Statistics Service
emoji: 🚀
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# FastAPI Statistics Service

This is a FastAPI application that computes descriptive statistics for a list of integers.

## Endpoint

### GET /stats

Example:

```text
/stats?values=1,2,3,4,5
```

### Response

```json
{
  "email": "chahatpawar666@gmail.com",
  "count": 5,
  "sum": 15,
  "min": 1,
  "max": 5,
  "mean": 3.0
}
```

## Features

- Computes statistics dynamically
- FastAPI backend
- Per-origin CORS policy
- Supports CORS preflight (`OPTIONS`)
- Adds `X-Request-ID` header
- Adds `X-Process-Time` header
- Ready for automated grading

## Running locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the server:

```bash
uvicorn main:app --host 0.0.0.0 --port 7860
```

Open:

```
http://127.0.0.1:7860/docs
```

to access the Swagger UI.