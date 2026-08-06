# Use a lightweight official Python runtime base image
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /code

# Copy the requirements file and install dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy everything else in your local directory (app.py, index, csv) into the container
COPY . .

# Hugging Face Spaces strictly requires containers to listen on port 7860
EXPOSE 7860

# Command to start your FastAPI server with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]