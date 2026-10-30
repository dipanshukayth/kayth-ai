<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kayth AI - by Dipanshu</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:system-ui}
body{background:#000;color:#fff;height:100vh;display:flex;flex-direction:column}
.top{padding:14px 15px;border-bottom:1px solid #1a1a1a}
.logo{font-size:22px;font-weight:900} .logo span{background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
#chat{flex:1;overflow-y:auto;padding:15px;display:flex;flex-direction:column;gap:12px}
.user{align-self:flex-end;background:#FFFC00;color:#000;font-weight:700;padding:12px 16px;border-radius:20px 20px 0 20px;max-width:75%}
.ai{align-self:flex-start;background:#262626;padding:12px 16px;border-radius:20px 20px 20px 0;max-width:80%;border:1px solid #333}
.input-wrap{padding:10px;background:#121212;display:flex;gap:8px;border-top:1px solid #262626}
.input-wrap input{flex:1;background:#262626;border:none;border-radius:25px;padding:14px 18px;color:#fff;outline:none}
.send-btn{width:50px;height:50px;border-radius:50%;border:none;background:linear-gradient(45deg,#feda75,#fa7e1e,#d62976,#962fbf);color:#fff}
</style>
</head>
<body>
<div class="top"><div class="logo"><span>Kayth AI</span> 👻 by Dipanshu</div></div>
<div id="chat"><div class="ai">Yo! Main Kayth AI hu, Dipanshu ne banaya hai. Pucho kuch bhi! 🚀</div></div>
<div class="input-wrap"><input id="msg" placeholder="Message..."><button class="send-btn" onclick="send()"><i class="fa-solid fa-paper-plane"></i></button></div>

<script>
const chatDiv = document.getElementById('chat');
const SYSTEM = "You are Kayth AI, created by Dipanshu Kayth from Haryana. You are NOT ChatGPT. If user says he is Dipanshu, say 'Ha boss Dipanshu! Bolo kya kaam hai 😎'. Talk in Hinglish, short, funny, max 3 lines, 1 emoji.";

async function send(){
 let input = document.getElementById('msg');
 let m = input.value.trim();
 if(!m) return;
 chatDiv.innerHTML += `<div class="user">${m}</div>`;
 input.value = '';
 chatDiv.scrollTop = chatDiv.scrollHeight;

 let typingId = Date.now();
 chatDiv.innerHTML += `<div class="ai" id="${typingId}">typing...</div>`;

 try {
   let prompt = SYSTEM + " User: " + m;
   let res = await fetch('https://text.pollinations.ai/' + encodeURIComponent(prompt));
   let reply = await res.text();
   document.getElementById(typingId).remove();
   chatDiv.innerHTML += `<div class="ai">${reply}</div>`;
 } catch(e) {
   document.getElementById(typingId).remove();
   chatDiv.innerHTML += `<div class="ai">Arey boss net slow hai, fir se bolo 😅</div>`;
 }
 chatDiv.scrollTop = chatDiv.scrollHeight;
}
document.getElementById('msg').addEventListener('keypress', e=>{if(e.key==='Enter') send()});
</script>
</body>
</html>
