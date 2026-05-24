"""
AI 废土大逃杀 — 弹幕驱动版
vs 原版：去掉每8秒固定轮询，改为弹幕/命令触发机制
    没有弹幕时角色待机，有弹幕时立即触发DeepSeek生成响应
"""
import os, time, threading, http.server, socketserver, json, random
from urllib.parse import urlparse, parse_qs
from openai import OpenAI

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise SystemExit("请设置环境变量 DEEPSEEK_API_KEY")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
COMMANDS_PATH = os.path.join(CURRENT_DIR, "commands.json")

# ===== 角色初始状态 =====
players = {
    "A": {"mbti": "ESTP (企业家)", "hp": 100, "weapon": "拳头", "status": "健康"},
    "B": {"mbti": "INFP (调停者)", "hp": 100, "weapon": "拳头", "status": "健康"},
    "C": {"mbti": "INTJ (建筑师)", "hp": 100, "weapon": "拳头", "status": "健康"},
    "D": {"mbti": "ENFP (竞选者)", "hp": 100, "weapon": "拳头", "status": "健康"},
    "E": {"mbti": "ISTJ (物流师)", "hp": 100, "weapon": "拳头", "status": "健康"}
}

# ===== 弹幕队列 =====
danmu_queue = []
danmu_lock = threading.Lock()

# ===== 时间追踪 =====
last_trigger_time = time.time()
IDLE_TIMEOUT = 5  # 5秒无弹幕则播报待机状态

# ===== JSON 读写工具 =====
def load_commands():
    try:
        if not os.path.exists(COMMANDS_PATH): return {}
        with open(COMMANDS_PATH, 'r', encoding='utf-8') as f: return json.load(f) or {}
    except: return {}

def save_commands(d):
    tmp = COMMANDS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, COMMANDS_PATH)

def write_script(script):
    json_path = os.path.join(CURRENT_DIR, "game_script.json")
    tmp_path = json_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, json_path)

# ===== 弹幕词云聚合 =====
def aggregate_danmu(danmu_list):
    """将弹幕聚合成关键词，传给DeepSeek"""
    if not danmu_list:
        return {}
    
    # 统计角色被提及次数
    role_mentions = {k: 0 for k in players.keys()}
    # 统计动作倾向
    action_trend = {"attack": 0, "scavenge": 0, "hide": 0, "run": 0, "defend": 0, "help": 0}
    target_mentions = {k: 0 for k in players.keys()}
    
    for msg in danmu_list:
        msg_upper = msg.upper()
        for rid in players.keys():
            if rid in msg_upper:
                role_mentions[rid] += 1
        for rid in players.keys():
            if rid in msg_upper:
                target_mentions[rid] += 1
        if any(w in msg for w in ["打", "杀", "攻", "attack", "atk"]):
            action_trend["attack"] += 1
        if any(w in msg for w in ["搜", "捡", "找", "scavenge", "item"]):
            action_trend["scavenge"] += 1
        if any(w in msg for w in ["躲", "藏", "hide", "run"]):
            action_trend["hide"] += 1
        if any(w in msg for w in ["跑", "逃", "撤"]):
            action_trend["run"] += 1
        if any(w in msg for w in ["守", "防", "defend"]):
            action_trend["defend"] += 1
        if any(w in msg for w in ["救", "帮", "奶", "help", "heal"]):
            action_trend["help"] += 1
    
    return {
        "role_mentions": sorted(role_mentions.items(), key=lambda x: -x[1])[:3],
        "action_trend": sorted(action_trend.items(), key=lambda x: -x[1])[:3],
        "target_mentions": sorted(target_mentions.items(), key=lambda x: -x[1])[:3],
        "raw_count": len(danmu_list)
    }

# ===== 弹幕模拟器 =====
def generate_mock_danmu():
    names = list(players.keys())
    events = [
        "天上掉下了辐射陨石！", "空投箱掉落在地图中央！",
        "地震发生了，地面裂开！", "废土上刮起了狂风！"
    ]
    mock_chats = [
        f"观众_{random.randint(100,999)}: 让 {random.choice(names)} 去打 {random.choice(names)}！",
        f"乐子人: {random.choice(names)} 赶紧去搜刮物资啊！",
        f"战术大师: {random.choice(names)} 快躲起来！",
        f"上帝视角: {random.choice(events)}"
    ]
    return mock_chats

# ===== DeepSeek 调用 =====
def ask_deepseek(story_context, danmu_analysis, is_idle=False):
    """根据弹幕分析和当前状态，生成下一段剧情"""
    
    if is_idle:
        system_prompt = """
        你是AI废土大逃杀的导演。当前没有观众弹幕，角色正在进行待机行动。
        请生成一段简短的待机描述，让角色做低强度的探索、休息或巡逻动作。
        JSON格式，不要多余文字，和之前一样。
        """
    else:
        system_prompt = """
        你是AI废土大逃杀的导演。观众弹幕已经用词云分析过了。
        角色的行动应该尽量贴近观众弹幕的倾向。
        JSON格式，不要多余文字。
        """
    
    user_content = json.dumps({
        "current_state": players,
        "context": story_context,
        "danmu_analysis": danmu_analysis
    }, ensure_ascii=False)
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.8
        )
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        print(f"DeepSeek调用失败: {e}")
        return None

# ===== 应用剧本到角色状态 =====
def apply_script(script):
    if not script or "characters" not in script:
        return
    
    commands = load_commands()
    chars = script.get("characters", {})
    
    # 优先应用用户命令
    for rid, cmd in commands.items():
        if rid in chars:
            chars[rid]['action'] = cmd.get('action', chars[rid].get('action'))
            if 'dialogue' in cmd:
                chars[rid]['dialogue'] = cmd.get('dialogue')
    save_commands({})
    
    # 更新血量、武器
    for name, info in chars.items():
        if name in players:
            players[name]["hp"] += info.get("hp_change", 0)
            if players[name]["hp"] <= 0:
                players[name]["hp"] = 0
                players[name]["status"] = "死亡"
            if info.get("new_weapon") and info["new_weapon"] not in ["...", "无"]:
                players[name]["weapon"] = info["new_weapon"]
    
    # 生成战报
    battle_log = []
    for name, info in chars.items():
        if name in players:
            line = f"{name} {players[name]['mbti']} 执行了 [{info.get('action')}]"
            if info.get('dialogue'):
                line += f' 说:"{info["dialogue"]}"'
            if info.get('hp_change', 0) != 0:
                line += f" HP变化 {info['hp_change']}"
            battle_log.append(line)
    script['battle_log'] = battle_log
    
    # 检查胜负
    alive = [n for n, p in players.items() if p['hp'] > 0]
    if len(alive) <= 1:
        script['game_over'] = True
        script['winner'] = alive[0] if alive else None
    
    write_script(script)

# ===== HTTP 服务器（接收前端指令和弹幕）=====
class Handler(http.server.BaseHTTPRequestHandler):
    def _json(self, code=200, data=None):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        if data:
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def do_GET(self):
        if self.path.startswith('/commands'):
            self._json(200, load_commands())
        elif self.path.startswith('/status'):
            self._json(200, {
                'players': players,
                'danmu_queue_size': len(danmu_queue),
                'last_trigger': last_trigger_time
            })
        else:
            self.send_response(404); self.end_headers()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith('/command'):
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            cmds = load_commands()
            cmds[body.get('role')] = body
            save_commands(cmds)
            self._json(200, {'ok': True})
        elif parsed.path.startswith('/danmu'):
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            with danmu_lock:
                danmu_queue.append(body.get('text', ''))
            self._json(200, {'ok': True, 'queue_size': len(danmu_queue)})
        else:
            self.send_response(404); self.end_headers()
    
    def log_message(self, *args): pass

def start_http():
    try:
        s = socketserver.ThreadingTCPServer(('127.0.0.1', 9001), Handler)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        print("🔌 HTTP服务器已启动: 127.0.0.1:9001")
    except Exception as e:
        print(f"⚠️ HTTP服务器启动失败: {e}")

# ===== 主循环 =====
def main():
    global last_trigger_time
    print("🚀 AI废土大逃杀 — 弹幕驱动版 已启动")
    print("   等待弹幕触发剧情… 无弹幕时角色会自动待机")
    start_http()
    
    # 初始化一个待机剧本
    init_script = {
        "world_event": "废土风吹过残垣断壁，5个幸存者在城市废墟中游荡。",
        "characters": {r: {"dialogue": "待命中…", "hp_change": 0, "action": "idle", "new_weapon": "..."} for r in players}
    }
    write_script(init_script)
    
    story_context = []
    round_count = 0
    
    while True:
        # 检查游戏是否结束
        alive = [n for n, p in players.items() if p["hp"] > 0]
        if len(alive) <= 1:
            print(f"\n🏆 游戏结束！幸存者: {alive if alive else '无人'}")
            final = {"world_event": "决赛结束", "game_over": True, "winner": alive[0] if alive else None}
            write_script(final)
            break
        
        # 检查弹幕队列和命令
        has_new_danmu = len(danmu_queue) > 0
        has_new_commands = bool(load_commands())
        time_since_last = time.time() - last_trigger_time
        is_idle = not (has_new_danmu or has_new_commands) and time_since_last >= IDLE_TIMEOUT
        
        if has_new_danmu or has_new_commands or is_idle:
            round_count += 1
            
            # 收集当前弹幕
            with danmu_lock:
                current_danmu = danmu_queue[:]
                danmu_queue.clear()
            
            # 如果没有真实弹幕且空闲，生成模拟弹幕
            if not current_danmu and is_idle:
                current_danmu = generate_mock_danmu()
                print(f"\n🕐 待机中（{time_since_last:.0f}秒无弹幕）")
            else:
                print(f"\n🎯 第{round_count}次触发 ({'弹幕' if has_new_danmu else '命令' if has_new_commands else '待机'})")
            
            # 统计弹幕
            analysis = aggregate_danmu(current_danmu)
            for msg in current_danmu[:5]:
                print(f"  📨 {msg}")
            if analysis['raw_count'] > 5:
                print(f"  …及{analysis['raw_count']-5}条其他弹幕")
            
            # 调用DeepSeek
            script = ask_deepseek(story_context[-3:] if story_context else [], analysis, is_idle=is_idle)
            if script:
                story_context.append(script)
                if len(story_context) > 10:
                    story_context = story_context[-10:]
                apply_script(script)
                print(f"🌍 {script.get('world_event','')}")
                for log in script.get('battle_log', []):
                    print(f"  📋 {log}")
            else:
                print("⚠️ 剧本生成失败")
            
            last_trigger_time = time.time()
        
        time.sleep(1.5)  # 每1.5秒检查一次

if __name__ == "__main__":
    main()
