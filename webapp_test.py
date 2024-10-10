from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    # Run the app on localhost, port 8080
    app.run(host='127.0.0.1', port=8080)