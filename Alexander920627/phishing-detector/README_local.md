# AI-Driven Phishing Email Detector API 🛡️

A lightweight, rule-based RESTful API designed to detect potential phishing emails. Built with **FastAPI** and **Python**, this microservice analyzes email contents and sender domains to provide a multi-dimensional threat assessment.

## 🚀 Features
- **Multi-layered Threat Detection**: Analyzes both email content and sender domains to classify threats into `Safe`, `Warning`, or `Critical`.
- **High Performance**: Asynchronous request handling powered by `Uvicorn` and `FastAPI`.
- **Data Validation**: Strict payload validation utilizing `Pydantic` to prevent malformed requests.

## 🛠️ Tech Stack
- **Framework**: FastAPI
- **Server**: Uvicorn
- **Language**: Python 3.x

## 💻 Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/Alexander-Tasi/phishing-detector-api.git
   cd phishing-detector-api
   ```

2. **Create a virtual environment & Install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Run the API server**
   ```bash
   uvicorn main:app --reload
   ```

4. **Test the API**
   Open your browser and navigate to [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to use the interactive Swagger UI.