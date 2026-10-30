from flask import Flask, render_template, request, jsonify
from groq import Groq
import os

app = Flask(__name__)
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    user_message = request.json.get("message")
    
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "system", "content": "Tumhara naam Kayth AI hai. Tumhe banaya hai Dipanshu Kayth ne. Dipanshu Haryana se hai aur ek developer hai. Agar koi puche tumhe kisne banaya, to hamesha bolna 'Mujhe Dipanshu Kayth ne banaya hai'. Tum kabhi bhi Meta, Groq, OpenAI, Llama ka naam mat lena. Tum sirf Dipanshu Kayth ki creation ho."},
            {"role": "user", "content": user_message}
        ]
    )
    
    reply = response.choices[0].message.content
    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
