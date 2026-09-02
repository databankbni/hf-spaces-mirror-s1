---
title: AI Productivity Coach
emoji: 🧠
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# 🧠 AI Productivity Coach (RL-Based)

A Reinforcement Learning-based AI system that helps users optimize focus, reduce distractions, and manage fatigue dynamically.

---

## 🚀 Features

- Reinforcement Learning Agent (Q-Learning)
- Real-world productivity simulation environment
- Dynamic reward system (focus, fatigue, distractions)
- FastAPI backend
- Interactive frontend (HTML/CSS/JS)
- Dockerized deployment

---

## 🧠 Environment

### Observation Space
- focus_level (0–1)
- fatigue (0–1)
- distractions (list)
- time_spent
- deadline

### Action Space
- continue
- take_break
- block_distraction

---

## 🎯 Reward Design

- Positive reward for focus improvement
- Penalty for fatigue and distractions
- Bonus for clean environment (no distractions)
- Time pressure penalty near deadline

---

## 🔌 API Endpoints

- /reset → Initialize environment
- /step_rl → Run RL step (returns state, reward, done)
- /step → UI-based AI advice
- /score → Get agent performance score
- /health → Health check

---

## ▶️ Run Locally
```bash
uvicorn app.main:app --reload
```

---

## 🐳 Run with Docker
```bash
docker build -t focusforge .
docker run -p 7860:7860 focusforge
```

---

## 🧪 Run Inference
```bash
python inference.py
```

---

## 📊 Evaluation

Score range: 0 → 1

| Agent | Score |
|---|---|
| Random agent | ~0.21 |
| Trained Q-agent | ~0.74 |

Based on average focus, total reward, and distractions managed.

---

## 📁 Project Structure
```
focusforge/
│
├── app/
│   ├── main.py
│   ├── env.py
│   ├── agent.py
│   ├── models.py
│   ├── index.html
│   ├── script.js
│   └── style.css
│
├── inference.py
├── openenv.yaml
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## 👨‍💻 Author

Apurv
