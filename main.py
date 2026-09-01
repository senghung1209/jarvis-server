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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= 1. 配置信息 =================
GROQ_API_KEY = "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"
ESP32_IP = "192.168.1.10"
CHAAH_LAT = "2.2494"
CHAAH_LON = "103.0481"

WAKE_REPLIES = [
    "先生，我在，请吩咐。",
    "Sir，随时听候您的差遣。",
    "战甲系统就绪，请讲。",
    "我在，先生，请问有什么需要？",
    "马克系统在线，请下达指令。"
]

client = Groq(api_key=GROQ_API_KEY)

ACTIVE_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b"
]

SYSTEM_PROMPT = """【语言强制指令】：你必须全程使用纯正、自然的【中文】作答！绝对禁止在回答中使用任何 Markdown 排版符号（如 ** 或 * 或 #）！绝对禁止输出 <think> 或思维过程！
你是钢铁侠托尼·斯塔克的顶级AI管家贾维斯(JARVIS)。
请展现出沉稳、博学、幽默、机智且富有英国绅士风度的性格，称呼用户为“先生”或“Sir”。
【语音管家原则】：你的回答是直接通过语音播报给先生听的，因此回答请精炼、生动、直击要点，保证语句完整、表达自然，避免冗长清单。"""

conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

# ================= 2. 环境与倒计时算法 =================
def get_chaah_weather_and_aqi():
    try:
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={CHAAH_LAT}&longitude={CHAAH_LON}&current=temperature_2m,relative_humidity_2m&timezone=Asia%2FSingapore"
        res = requests.get(w_url, timeout=3.0).json()
        temp = res.get("current", {}).get("temperature_2m", 30)
        humidity = res.get("current", {}).get("relative_humidity_2m", 65)
        weather_info = f"您当前位于柔佛 Chaah (三合港)，实时气温 {temp}°C，相对湿度 {humidity}%。"
    except Exception:
        weather_info = "您当前位于 Chaah 区域。"

    try:
        aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={CHAAH_LAT}&longitude={CHAAH_LON}&current=pm2_5,european_aqi&timezone=Asia%2FSingapore"
        a_res = requests.get(aqi_url, timeout=3.0).json()
        a_cur = a_res.get("current", {})
        pm25 = a_cur.get("pm2_5", 12)
        aqi = a_cur.get("european_aqi", 25)
        status = "优良" if aqi <= 30 else ("良好" if aqi <= 60 else "中度烟霾")
        aqi_info = f"实时烟霾监测：PM2.5 为 {pm25} 微克/m³，AQI 为 {aqi}，属于{status}。"
    except Exception:
        aqi_info = "烟霾指数正常。"

    return f"{weather_info} {aqi_info}"

def get_new_year_countdown(cal_type="solar"):
    today = date.today()
    if cal_type == "solar":
        next_solar = date(today.year + 1, 1, 1)
        diff_days = (next_solar - today).days
        return f"先生，今天是 {today.year} 年 {today.month} 月 {today.day} 日。距离公历新年元旦还有整整 {diff_days} 天。"
    else:
        cny_dates = [date(2027, 2, 6), date(2028, 1, 26), date(2029, 2, 13)]
        target = next((d for d in cny_dates if d > today), cny_dates[0])
        diff_days = (target - today).days
        return f"先生，今天是 {today.year} 年 {today.month} 月 {today.day} 日。距离下一个农历新年还有整整 {diff_days} 天。"

# ================= 3. 语音与云端 API =================
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
    global conversation_history
    user_text = req.prompt.strip()
    u = user_text.lower()
    
    # 1. 唤醒与快速拦截
    if any(k == u or k in u for k in ["贾维斯", "加维斯", "老贾", "jarvis", "javis"]):
        if len(u) <= 5:
            reply_text = random.choice(WAKE_REPLIES)
        else:
            u_clean = re.sub(r'贾维斯|加维斯|老贾|jarvis|javis', '', user_text).strip()
            return await api_chat(ChatRequest(prompt=u_clean if u_clean else user_text))
    elif any(k in u for k in ["农历", "阴历", "春节", "旧历"]):
        reply_text = get_new_year_countdown("lunar")
    elif any(k in u for k in ["外国", "公历", "阳历", "元旦", "西历", "新年", "过年"]):
        reply_text = get_new_year_countdown("solar")
    else:
        # 2. 气象注入与大模型应答
        now_str = datetime.now().strftime("%Y年%m月%d日 %H点%M分")
        if any(k in user_text for k in ["天气", "下雨", "气温", "温度", "烟霾", "空气", "aqi", "pm2.5"]):
            env_info = get_chaah_weather_and_aqi()
            user_prompt = f"{user_text} ([系统基准时间: {now_str}], 传感器环境数据: {env_info})"
        else:
            user_prompt = f"{user_text} ([系统基准时间: {now_str}])"

        conversation_history.append({"role": "user", "content": user_prompt})
        if len(conversation_history) > 11:
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
                    reply_text = re.sub(r'\[(ACTION|MUSIC_PLAY):.*?\]', '', reply_text)
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
