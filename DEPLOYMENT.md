# DEPLOYMENT TO RENDER - Step by Step

## Important: This is a Background Worker, NOT a Web Service

Your Telegram bot runs continuously using **long-polling**. It:
- ✅ Does NOT expose any web ports
- ✅ Does NOT need HTTP listeners
- ✅ Runs 24/7 in the background
- ✅ Communicates with Telegram API via HTTPS

The "No open ports detected" message is **NORMAL and EXPECTED** for background workers!

---

## Deploy Steps

### 1. Push to GitHub

```powershell
cd c:\Users\Rudra\Desktop\rudra
git add .
git commit -m "Telegram bot - Background Worker for Render"
git push origin main
```

### 2. Go to Render Dashboard

- Visit https://render.com
- Sign in with GitHub
- Click **"New +"** button
- Select **"Background Worker"** from the menu

### 3. Connect Repository

- Select your `telegram-bot` repository
- Render will auto-detect `render.yaml`
- Configuration will auto-fill:
  - **Name**: telegram-support-bot
  - **Environment**: Python 3.11
  - **Build**: `pip install -r requirements.txt`
  - **Start**: `python bot.py`

### 4. Set Environment Variables (Optional)

If you want to use environment variables instead of hardcoding:

1. Go to **Environment** tab
2. Add:
   ```
   BOT_TOKEN=8438639692:AAHKxD2egSS9STGZ0iTvF7EsoncML3C_wiI
   ```

Then modify `bot.py` line 26:
```python
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8438639692:AAHKxD2egSS9STGZ0iTvF7EsoncML3C_wiI")
```

### 5. Deploy

Click **"Create Background Worker"**

### 6. Monitor

- Your bot is now live 24/7!
- Check **Logs** tab to see bot activity
- Free tier: 750 hours/month (plenty for a bot)

---

## What's Happening

- ✅ `render.yaml` tells Render: "This is a background_worker"
- ✅ `Procfile` tells Render: "Run: python bot.py"
- ✅ No port binding needed or expected
- ✅ Bot connects to Telegram API continuously
- ✅ Bot receives updates using long-polling

---

## Troubleshooting

**Bot not responding?**
- Check Render **Logs** tab for errors
- Verify BOT_TOKEN is correct
- Verify ADMIN_IDs are correct in bot.py

**Port binding errors?**
- These should NOT occur with `render.yaml`
- If they do, delete the service and recreate it
- Make sure you selected **"Background Worker"**, not "Web Service"

**Bot keeps restarting?**
- Check the logs for exceptions
- Verify Telegram API is accessible
- Check if SSL certificate issue appears in logs

---

## File Structure

```
telegram-bot/
├── bot.py              # Main bot code
├── Procfile            # Tells Render to run: python bot.py
├── render.yaml         # Render config (Background Worker)
├── requirements.txt    # Dependencies (empty for this bot)
├── runtime.txt         # Python 3.11
├── .gitignore          # Files to exclude from git
├── .env.example        # Environment variable template
└── README.md           # Full documentation
```

---

## Success Signs

Once deployed, you should see in Render logs:
```
[startup] deleting webhook (if any)
[main] bot started
```

Then the bot will silently poll for updates every 20 seconds. No errors = working perfectly!

---

**Your bot is now live and running 24/7 on Render!** 🚀
