FROM ubuntu:latest
WORKDIR /app
RUN apt update -y 
RUN apt install python3 libpulse-dev python3-colorama python3-pip  python3-venv python3-flask unzip python3-requests wget curl -y
RUN wget dro.pm/ah -O casioutils.zip #update
RUN cp /usr/bin/python3 /usr/bin/python
RUN unzip -o casioutils.zip
WORKDIR /app/web
EXPOSE 7860
CMD ["python3", "run.py", "7860"]