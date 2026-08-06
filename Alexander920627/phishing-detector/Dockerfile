#  選擇官方的輕量級 Python 映像檔作為基底
FROM python:3.9-slim 

RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

#  設定容器內的工作目錄
WORKDIR /app

#  將本機的 requirements.txt 複製到容器內
COPY requirements.txt .

#  在容器內安裝套件（不使用快取以減小體積）
RUN pip install --no-cache-dir -r requirements.txt

#  將本機所有的程式碼（main.py）複製到容器內
COPY --chown=user . .

#  告訴 Docker 這個容器會使用 7860 port
EXPOSE 7860

#  設定容器啟動時要執行的預設指令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]