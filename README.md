# AI 废土大逃杀

本仓库包含一个本地化的模拟直播系统：Python 后端（`brain.py`）负责生成回合剧本并写入 `game_script.json`，前端静态页面 `index.html` 轮询并可显示实时战况。

重要安全说明
- 请不要将你的 DeepSeek/OpenAI API Key 提交到公共仓库。项目已将 API Key 从 `brain.py` 中移出，改为从环境变量读取 `DEEPSEEK_API_KEY`。
- 建议在本地创建一个 `.env` 文件并把密钥写入，示例见 `.env.example`。仓库里已包含 `.gitignore`，会忽略 `.env` 和 `game_script.json`。

本地运行（示例）
1. 在仓库目录创建 `.env` 并填入：

```bash
cp .env.example .env
# 编辑 .env，把 your_deepseek_api_key_here 换成真实的 KEY
```

2. 启动后端（会每 8 秒生成一回合并写 `game_script.json`）：

```bash
python3 brain.py
```

3. 在另一个终端用本地静态服务器打开前端（避免 file:// 限制）：

```bash
python3 -m http.server 8000
# 在浏览器打开 http://localhost:8000/index.html
```

把仓库推送到 GitHub（手动步骤）
1. 本地初始化 git 并提交：

```bash
git init
git add .
git commit -m "Initial commit: remove hardcoded API key, add README and .env.example"
```

2. 在 GitHub 上新建仓库（在网页上），然后把远程添加并推送：

```bash
git remote add origin git@github.com:YOUR_USERNAME/YOUR_REPO.git
git branch -M main
git push -u origin main
```

把密钥放到 GitHub Secrets（如果你使用 GitHub Actions）
- 打开仓库设置 -> Secrets -> Actions -> New repository secret，名称使用 `DEEPSEEK_API_KEY`。

已实现：本仓库已提供一个本地命令接口，后端会在每回合生成后优先合并这些指令再写入 `game_script.json`。

- 启动 `brain.py` 后会同时监听本地端口 `9001`。
- 发送指令示例（POST 到 `/command`）：

```bash
curl -X POST http://127.0.0.1:9001/command -H "Content-Type: application/json" \
	-d '{"role":"A","action":"attack","target":"B"}'
```

- 查看当前未消费指令（GET `/commands`）：

```bash
curl http://127.0.0.1:9001/commands
```

行为说明：后端会把命令当作优先项合并到 DeepSeek 生成的 `characters` 字段上，并在合并后清空命令存储（一次性消费）。前端已有的即时覆盖机制仍然保留用于展示。
