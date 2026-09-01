import time
import requests
import json
import os
import re
import sys
import asyncio
import urllib.parse
import urllib.request
import random
from datetime import datetime, date
import edge_tts
from groq import Groq
from fastapi import FastAPI, Response
from pydantic import BaseModel

app = FastAPI()

GROQ_API_KEY = "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"
client = Groq(api_key=GROQ_API_KEY)

WAKE_REPLIES = [
    "先生，我在，请吩咐。",
    "Sir，随时听候您的差遣。",
    "战甲系统就绪，请讲。",
    "我在，先生，请问有什么需要？",
    "马克系统在线，请下达指令。"
]

ACTIVE_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b"
]

SYSTEM_PROMPT = """【语言强制指令】：你必须全程使用纯正、自然的【中文】作答！绝对禁止在回答中使用任何 Markdown 排版符号（如 ** 或 * 或 #）！绝对禁止输出 <think> 或思维过程！
你是钢铁侠托尼·斯塔克的顶级AI管家贾维斯(JARVIS)。
请展现出沉稳、博学、幽默、机智且富有英国绅士风度的性格，称呼用户为“先生”或“Sir”。
【语音管家原则】：你的回答是直接通过语音播报给先生听的，因此回答请精炼、生动、直击要点，保证语句完整、表达自然。"""

conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

async def _gen_audio(text, output_file):
    communicate = edge_tts.Communicate(text, "zh-CN-YunxiNeural", volume="+100%", rate="+15%")
    await communicate.save(output_file)

@app.get("/wake")
async def api_wake():
    text = random.choice(WAKE_REPLIES)
    audio_path = "cloud_wake.mp3"
    await _gen_audio(text, audio_path)
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    if os.path.exists(audio_path):
        os.remove(audio_path)
    return Response(content=audio_bytes, media_type="audio/mpeg")

class ChatRequest(BaseModel):
    prompt: str

@app.post("/chat")
async def api_chat(req: ChatRequest):
    user_text = req.prompt
    now_str = datetime.now().strftime("%Y年%m月%d日 %H点%M分")
    user_prompt = f"{user_text} ([系统基准时间: {now_str}])"
    
    conversation_history.append({"role": "user", "content": user_prompt})
    if len(conversation_history) > 11:
        global conversation_history
        conversation_history = [conversation_history[0]] + conversation_history[-10:]

    reply_text = "抱歉先生，网络神经链路刚刚产生轻微波动。"
    for target_model in ACTIVE_MODELS:
        try:
            chat_completion = client.chat.completions.create(
                messages=conversation_history,
                model=target_model,
                temperature=0.6,
                max_tokens=2048,
                timeout=15
            )
            raw_reply = chat_completion.choices[0].message.content
            if raw_reply and raw_reply.strip():
                reply_text = re.sub(r'<think>.*?</think>', '', raw_reply, flags=re.DOTALL)
                reply_text = reply_text.replace('*', '').replace('#', '').strip()
                conversation_history.append({"role": "assistant", "content": reply_text})
                break
        except Exception:
            continue

    audio_path = "cloud_chat.mp3"
    await _gen_audio(reply_text, audio_path)
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()
    if os.path.exists(audio_path):
        os.remove(audio_path)
    return Response(content=audio_bytes, media_type="audio/mpeg")

@app.get("/")
async def root():
    return {"status": "Jarvis Cloud Core Online"}
