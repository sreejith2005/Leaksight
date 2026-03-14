# How to Start LeakSight Locally

## Quick Start

Open **two separate terminals** in the project folder:  
`c:\Users\LENOVO\Downloads\Leaksight v1 -1`

### Terminal 1 — Backend (port 8000)

```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --port 8000
```

### Terminal 2 — Frontend (port 5173)

```powershell
cd frontend
npm run dev
```

### Verify

- Backend: open http://localhost:8000/api/v1/health → should show `{"status":"ok"}`
- Frontend: open http://localhost:5173

### Stop

Press `Ctrl+C` in the respective terminal.

---

## How Long Do They Stay Running?

**Both servers run indefinitely** — they do NOT auto-shutdown or timeout. They will keep running as long as:

1. The terminal window stays open (don't close the terminal)
2. Your computer stays on (not sleeping/hibernating)
3. You don't press Ctrl+C in that terminal
4. Nothing crashes (rare — if it does, just restart)

### When you WILL need to restart:

| Situation | Restart needed? |
|-----------|----------------|
| Computer restarted / woke from sleep | **Yes — both** |
| Terminal window was closed | **Yes — whichever was closed** |
| You pressed Ctrl+C | **Yes — whichever you stopped** |
| Edited a backend `.py` file | **No** — `--reload` flag auto-restarts it |
| Edited a frontend `.tsx`/`.css` file | **No** — Vite HMR auto-updates the browser |
| Installed a new Python package | **Yes — backend only** |
| Ran `npm install` in frontend | **Yes — frontend only** |
| Just left it running overnight | **No** — it stays up |

### TL;DR

You only need to restart when your computer sleeps/restarts or you close the terminal. During a normal work session, start both once and they stay up all day.
