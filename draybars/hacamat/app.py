from flask import Flask, render_template
import os

# Parantezlerin kapandığına ve virgüllere dikkat:
app = Flask(__name__, template_folder='templates') 

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port)