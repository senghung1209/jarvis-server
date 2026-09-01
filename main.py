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

# ================= 1. 配置信息 =================
GROQ_API_KEY = "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"
ESP32_IP = "192.168.0.130"
CHAAH_LAT = "2.2494"
CHAAH_LON = "103.0481"

WAKE_WORDS = [
    "贾维斯", "加维斯", "家维斯", "查维斯", "扎维斯", "佳维斯", "贾维", "加维",
    "jarvis", "javis", "jarvi", "javi", "老贾", "管家", "小贾", "贾"
]

WAKE_REPLIES = [
    "先生，我在，请吩咐。",
    "Sir，随时听候您的差遣。",
    "战甲系统就绪，请讲。",
    "我在，先生，请问有什么需要？",
    "马克系统在线，请下达指令。"
]

client = Groq(api_key=GROQ_API_KEY)

helmet_state = {
    "mask": "closed",
    "combat": False,
    "power": True
}

ACTIVE_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b"
]

# ================= 2. 硬件控制与状态转换 =================
def trigger_esp32(action):
    url = f"http://{ESP32_IP}/cmd?action={action}"
    print(f"[Hardware Action]: 正在向 {ESP32_IP} 发送指令 -> {action}")
    for attempt in range(2):
        try:
            res = requests.get(url, timeout=2.0)
            if res.status_code == 200:
                print(f"[Hardware Success]: {action} 执行成功 -> {res.text.strip()}")
                return True
        except Exception as e:
            if attempt == 1:
                print(f"[Hardware Warning]: ESP32 通信异常 ({e})")
            time.sleep(0.05)
    return False

def execute_helmet_action(action: str):
    global helmet_state
    if action == "open_full":
        if helmet_state["mask"] == "closed":
            trigger_esp32("s1")
            helmet_state["mask"] = "full"
        elif helmet_state["mask"] == "multi":
            trigger_esp32("s2")
            time.sleep(1.8)
            trigger_esp32("s1")
            helmet_state["mask"] = "full"

    elif action == "open_multi":
        if helmet_state["mask"] == "closed":
            trigger_esp32("s2")
            helmet_state["mask"] = "multi"
        elif helmet_state["mask"] == "full":
            trigger_esp32("s1")
            time.sleep(1.8)
            trigger_esp32("s2")
            helmet_state["mask"] = "multi"

    elif action == "close_full":
        if helmet_state["mask"] == "full":
            trigger_esp32("s1")
            helmet_state["mask"] = "closed"
        elif helmet_state["mask"] == "multi":
            trigger_esp32("s2")
            helmet_state["mask"] = "closed"

    elif action == "launch_mode":
        if not helmet_state["combat"]:
            trigger_esp32("s3")
            helmet_state["combat"] = True
        if helmet_state["mask"] != "closed":
            if helmet_state["mask"] == "full":
                trigger_esp32("s1")
            else:
                trigger_esp32("s2")
            helmet_state["mask"] = "closed"

    elif action == "toggle_combat":
        trigger_esp32("s3")
        helmet_state["combat"] = not helmet_state["combat"]

    elif action == "system_shutdown":
        if helmet_state["mask"] != "closed":
            if helmet_state["mask"] == "full":
                trigger_esp32("s1")
            else:
                trigger_esp32("s2")
            helmet_state["mask"] = "closed"
            time.sleep(1.2)
        if helmet_state["combat"]:
            trigger_esp32("s3")
            helmet_state["combat"] = False
            time.sleep(0.4)
        trigger_esp32("s4")
        helmet_state["power"] = False

    elif action == "toggle_power":
        trigger_esp32("s4")
        helmet_state["power"] = not helmet_state["power"]

# ================= 3. 环境数据与倒计时 =================
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

def parse_seek_seconds(text: str):
    t = text.lower()
    sec_match = re.search(r'(\d+)\s*秒', t)
    if sec_match:
        return int(sec_match.group(1))
    if "二十秒" in t or "20秒" in t:
        return 20
    elif "三十秒" in t or "30秒" in t or "半分钟" in t:
        return 30
    elif "一分钟" in t or "60秒" in t:
        return 60
    return 10

def parse_timer_seconds(text: str):
    t = text.lower()
    sec_match = re.search(r'(\d+)\s*秒', t)
    if sec_match:
        return int(sec_match.group(1))
    min_match = re.search(r'(\d+)\s*(?:分钟|分)', t)
    if min_match:
        return int(min_match.group(1)) * 60
    if "十秒" in t or "10秒" in t:
        return 10
    elif "三十秒" in t or "半分钟" in t:
        return 30
    elif "一分钟" in t or "1分钟" in t:
        return 60
    return None

def get_new_year_countdown(cal_type="solar"):
    today = date.today()
    if cal_type == "solar":
        next_solar = date(today.year + 1, 1, 1)
        diff_days = (next_solar - today).days
        return f"先生，今天是 {today.year} 年 {today.month} 月 {today.day} 日。距离国际通用的公历新年元旦（{next_solar.year} 年 1 月 1 日）还有整整 {diff_days} 天。"
    else:
        cny_dates = [date(2027, 2, 6), date(2028, 1, 26), date(2029, 2, 13)]
        target = next((d for d in cny_dates if d > today), cny_dates[0])
        diff_days = (target - today).days
        return f"先生，今天是 {today.year} 年 {today.month} 月 {today.day} 日。距离下一个农历新年（公历 {target.year} 年 {target.month} 月 {target.day} 日）还有整整 {diff_days} 天。"

# ================= 4. 大脑与本地意图精准拦截 =================
SYSTEM_PROMPT = """【语言强制指令】：你必须全程使用纯正、自然的【中文】作答！绝对禁止在回答中使用任何 Markdown 排版符号（如 ** 或 * 或 #）！绝对禁止输出 <think> 或思维过程！
你是钢铁侠托尼·斯塔克的顶级AI管家贾维斯(JARVIS)。
请展现出沉稳、博学、幽默、机智且富有英国绅士风度的性格，称呼用户为“先生”或“Sir”。
【语音管家原则】：你的回答是直接通过语音播报给先生听的，因此回答请精炼、生动、直击要点（推荐类问题推荐 2 到 3 个最经典的机型或方案即可），保证语句完整、表达自然，避免冗长清单。

【成语接龙规则】：
当与先生玩成语接龙时，快速接上精准成语并请先生继续。

【强制动作规则】：
只要先生提到以下词汇或需求，必须在回复末尾附带对应标签，立即执行动作：
- 打开头盔/开盔/全开/吃东西/肚子饿/我饿了/饿了/口渴/喝水/打包/饭菜/开面罩/头盔 -> [ACTION:open_full]
- 闷热/透气/散热/分段变形/心很热/好热/出汗 -> [ACTION:open_multi]
- 关上头盔/合上/关闭面罩/关盔/防御/防风/很冷/好冷/冷了/吃完了/饱了 -> [ACTION:close_full]
- 出击/起飞/全功率升空 -> [ACTION:launch_mode]
- 发现敌人/准备战斗/开启红光/警戒 -> [ACTION:toggle_combat]
- 关闭/关闭系统/关机/全关/休眠/晚安/睡觉/断电 -> [ACTION:system_shutdown]
- 停止播放/暂停/暂停音乐/别放了/关掉音乐/安静 -> [ACTION:stop_music]
- 点歌/放歌/播放音乐（提取歌名或歌手） -> [MUSIC_PLAY:任贤齐 心太软]
如果是普通闲聊或咨询，正常用中文幽默回答即可，不要附带任何标记。"""

conversation_history = [{"role": "system", "content": SYSTEM_PROMPT}]

def clean_reply_text(text):
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'\(Self-Correction.*?\)', '', text, flags=re.DOTALL)
    text = re.sub(r'(?i)output\s*[:*]*', '', text)
    text = re.sub(r'(?i)[-*]?\s*draft\s*[:*]*', '', text)
    text = text.replace('*', '').replace('#', '')
    return text.strip()

def fast_local_dispatch(user_text):
    u = user_text.lower()
    
    # 1. 公历与农历新年倒计时
    if any(k in u for k in ["外国", "公历", "阳历", "元旦", "西历"]):
        return ("countdown", get_new_year_countdown("solar"))
    elif any(k in u for k in ["农历", "阴历", "春节", "旧历"]):
        return ("countdown", get_new_year_countdown("lunar"))
    elif "新年" in u or "过年" in u:
        return ("countdown", get_new_year_countdown("solar"))

    # 2. 一键全关 / 关闭 / 休眠
    elif any(k == u for k in ["关闭", "全关", "关机", "休眠", "睡觉", "晚安", "关掉", "退出"]) or any(k in u for k in ["关闭系统", "断电", "关闭战甲", "退下"]):
        execute_helmet_action("system_shutdown")
        return ("shutdown", "好的先生，已为您执行全面关闭指令。音乐已停，战甲进入深度休眠，晚安，Sir。")

    # 3. 音量指令拦截
    elif any(k in u for k in ["小声", "小一点", "声音小", "音量小", "调小", "降音量"]):
        return ("vol", "已为您调低系统音量，先生。")
    elif any(k in u for k in ["大声", "大一点", "声音大", "音量大", "调大", "加音量"]):
        return ("vol", "已为您调高系统音量，先生。")
    elif "静音" in u:
        return ("vol", "已将系统静音，先生。")

    # 4. 快进 / 快退控制
    elif any(k in u for k in ["快进", "前进", "往前"]):
        secs = parse_seek_seconds(user_text)
        return ("seek", f"已为您快进 {secs} 秒。")
    elif any(k in u for k in ["快退", "倒退", "后退", "往后"]):
        secs = parse_seek_seconds(user_text)
        return ("seek", f"已为您倒退 {secs} 秒。")

    # 5. 闹钟 / 倒计时
    elif any(k in u for k in ["闹钟", "倒计时", "提醒我", "定时"]):
        secs = parse_timer_seconds(user_text)
        if secs:
            return ("alarm", f"已为您启动 {secs} 秒倒计时提醒，先生。")

    # 6. 停止/暂停音乐
    elif any(k in u for k in ["停止", "暂停", "不听了", "别播了", "别放了", "关掉音乐", "别唱了", "安静", "关音乐"]):
        return ("music_stop", "已为您暂停并切断所有音乐播放，先生。")

    # 7. 点歌/切歌
    elif any(k in u for k in ["下一首", "换一首", "切歌", "下一曲", "换歌"]):
        return ("music_play", "好的先生，正在为您切换到《华语流行热门金曲》。")
    elif any(k in u for k in ["播放", "放歌", "听歌", "放首", "来首", "点歌", "换首", "听"]):
        song_kw = re.sub(r'播放|放歌|听歌|放首|来首|点歌|换首|我想听|的一首|的歌|音乐|歌|听', '', user_text).strip()
        if not song_kw:
            song_kw = "经典流行音乐"
        return ("music_play", f"好的先生，正在为您播放《{song_kw}》。")

    # 8. 面罩全开
    elif any(k in u for k in ["头盔", "开盔", "打开", "全开", "饿", "吃", "喝", "渴", "打包", "饭", "看清", "开面罩", "打开面罩"]):
        if any(close_k in u for close_k in ["关", "合", "闭"]):
            execute_helmet_action("close_full")
            return ("helmet", "好的先生，面罩已合上。")
        else:
            execute_helmet_action("open_full")
            return ("helmet", "好的先生，面罩已为您全开。")

    # 9. 分段散热
    elif any(k in u for k in ["热", "闷", "透气", "散热", "变形", "分段", "出汗"]):
        execute_helmet_action("open_multi")
        return ("helmet", "已为您开启分段散热模式，先生。")

    # 10. 合罩关闭
    elif any(k in u for k in ["关上", "合上", "关头盔", "关盔", "合面罩", "防御", "冷", "吃完", "饱"]):
        execute_helmet_action("close_full")
        return ("helmet", "防御装甲已闭合，先生。")

    # 11. 战斗红光
    elif any(k in u for k in ["战斗", "红光", "敌人", "警报", "危险", "警戒"]):
        execute_helmet_action("toggle_combat")
        return ("helmet", "战斗戒备状态已切换，先生。")

    # 12. 全功率起飞
    elif any(k in u for k in ["出击", "起飞", "升空"]):
        execute_helmet_action("launch_mode")
        return ("helmet", "推进器全功率加载，准备升空，Sir！")

    return (None, None)

def ask_jarvis_ai(user_text):
    global conversation_history, ACTIVE_MODELS
    
    now_str = datetime.now().strftime("%Y年%m月%d日 %H点%M分")
    extra_info = f"[系统基准时间: {now_str}]"
    
    if any(k in user_text for k in ["天气", "下雨", "气温", "温度", "烟霾", "空气", "aqi", "pm2.5"]):
        real_env_info = get_chaah_weather_and_aqi()
        user_prompt = f"{user_text} ({extra_info}, 战甲传感器真实环境数据: {real_env_info})"
    else:
        user_prompt = f"{user_text} ({extra_info})"

    conversation_history.append({"role": "user", "content": user_prompt})
    if len(conversation_history) > 11:
        conversation_history = [conversation_history[0]] + conversation_history[-10:]

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
            if not raw_reply or not raw_reply.strip():
                continue

            action_match = re.search(r'\[ACTION:\s*([a-zA-Z_]+)\s*\]', raw_reply)
            clean_reply = re.sub(r'\[(ACTION|MUSIC_PLAY):.*?\]', '', raw_reply)
            clean_reply = clean_reply_text(clean_reply)

            if not clean_reply:
                continue

            if action_match:
                action_name = action_match.group(1).strip()
                execute_helmet_action(action_name)

            conversation_history.append({"role": "assistant", "content": clean_reply})
            return clean_reply
        except Exception as e:
            print(f"[*] 模型 {target_model} 请求异常: {e}")
            continue

    return "抱歉先生，网络神经链路刚刚产生轻微波动，请问您刚才吩咐的是？"

# ================= 5. 云端输出与音频引擎 =================
async def _gen_audio(text, output_file):
    communicate = edge_tts.Communicate(text, "zh-CN-YunxiNeural", volume="+100%", rate="+15%")
    await communicate.save(output_file)

@app.get("/wake")
async def api_wake():
    reply_text = random.choice(WAKE_REPLIES)
    temp_audio = "cloud_wake.mp3"
    await _gen_audio(reply_text, temp_audio)
    with open(temp_audio, "rb") as f:
        audio_bytes = f.read()
    if os.path.exists(temp_audio):
        os.remove(temp_audio)
    return Response(content=audio_bytes, media_type="audio/mpeg")

class ChatRequest(BaseModel):
    prompt: str

@app.post("/chat")
async def api_chat(req: ChatRequest):
    user_text = req.prompt.strip()
    
    # 1. 优先走 0.001 秒本地毫秒级逻辑拦截
    act_type, act_val = fast_local_dispatch(user_text)
    if act_type is not None:
        reply_text = act_val
    else:
        # 2. 无匹配规则时走 Groq 深度大模型大脑
        reply_text = ask_jarvis_ai(user_text)

    temp_audio = "cloud_chat.mp3"
    await _gen_audio(reply_text, temp_audio)
    with open(temp_audio, "rb") as f:
        audio_bytes = f.read()
    if os.path.exists(temp_audio):
        os.remove(temp_audio)
    return Response(content=audio_bytes, media_type="audio/mpeg")

@app.get("/")
async def root():
    return {"status": "Jarvis Cloud Core Online"}
