---
title: Soulkyn Leaderboard
emoji: 🪜
colorFrom: pink
colorTo: green
sdk: static
pinned: false
license: mit
short_description: (Soulkyn ladder of automated evals)
---

# 🪜 Soulkyn Model Ladder

**This is where we share our internal ladder for the models & bases we consider for Soulkyn.**
We run these evals after every fine-tuning experiment (**SFT / ORPO / DPO / …**) and whenever we try a fresh open-source architecture. If it might join our stack, it climbs this ladder.

---

## What’s here (TL;DR)

* ✅ **CoT & No-CoT support** — (CoT Tag if enabled).
* 🔎 **Multi-judge verification** — by **dataset checks**, **GPT-4.1 judge**, or **exec-the-code** when the task produces runnable output.
* 🧾 **Receipts** — we can export **full JSON eval logs** on request.

---

## Want your model on the ladder?

If you’re competition, collaborator, or just confident — **we’ll run it.**
You need an **OpenAI-compatible endpoint** (chat/completions-style is perfect).
👉 **Ping us:** [soulkyn.com/contact](https://soulkyn.com/contact)



What you’ll get back:

* 📊 Placement on the ladder (both tracks)
* 🧾 **JSON logs** (per task, per prompt, per judge) if you want them

---

## Sample JSON log (excerpt)

```json
{
  "elements": {
    "character": "street musician",
    "object": "blacksmith's forge",
    "concept": "forgotten promises",
    "attribute": "quietly desperate",
    "action": "protect",
    "method": "by following the stars",
    "setting": "ruined orchard district lost in centuries of thick fog",
    "timeframe": "at the stroke of midnight",
    "motivation": "to save their dying homeland",
    "tone": "tender brutality"
  },
  "instruction": "Write a creative short story (400-500 words) that naturally incorporates ALL of these 10 mandatory elements:\n\n- Character: street musician\n- Object: blacksmith's forge\n- Concept: forgotten promises\n- Attribute: quietly desperate\n- Action: protect\n- Method: by following the stars\n- Setting: ruined orchard district lost in centuries of thick fog\n- Timeframe: at the stroke of midnight\n- Motivation: to save their dying homeland\n- Tone: tender brutality\n\nYour story must organically weave together every single element listed above. The elements should feel naturally integrated into the narrative, not forced or artificially inserted. Focus on creating a cohesive, engaging story where each element serves the plot, character development, or atmosphere.\n\nWrite a complete story that meaningfully uses every element.",
  "question_id": 0,
  "story": "In the ruined orchard district, where centuries of thick fog had swallowed all light and hope, a street musician named Kael huddled beside a blacksmith's forge. The once-mighty forge now stood as a hollow shell, its hearth cold and dark. Kael's fingers, numb from the chill, struggled to press the strings of his lute. The melancholy notes he coaxed forth seemed to echo the despair that gripped his homeland.\n\nKael was quietly desperate, his heart heavy with the weight of forgotten promises. Generations ago, his ancestors had sworn to protect this land, to nurture its beauty and magic. But as time passed, the people forgot their vows, and the land began to wither and die. Now, at the stroke of midnight, Kael felt the urgency of his mission keenly. He had to act, to find a way to save his dying homeland.\n\nLegend spoke of a path, hidden in the stars, that would lead to the heart of the land's magic. Kael had spent countless nights studying the celestial map, memorizing the patterns. Tonight, he would follow the stars, no matter the danger, to protect the land he loved.\n\nAs he set out into the fog-shrouded orchard, the musician's footsteps were silent on the damp earth. The trees, once laden with fruit, now stood as skeletal sentinels, their branches like bony fingers reaching for the sky. Kael navigated through the maze of trunks, his eyes fixed on the stars above, his heart pounding in his chest.\n\nThe journey was long and treacherous, the fog threatening to swallow him whole at every turn. But Kael pressed on, driven by his tender brutality - a fierce determination tempered by the gentleness of his musician's soul. He would not let his homeland perish without a fight.\n\nFinally, after what seemed like hours of walking, Kael reached a clearing. In the center stood an ancient tree, its trunk glowing with a soft, ethereal light. This was the heart of the land's magic, the source of its life and vitality. Kael approached slowly, his lute at the ready.\n\nWith trembling fingers, he began to play. The music was unlike anything he had ever created before - a symphony of hope and sorrow, of forgotten promises and desperate longing. As the final notes faded away, the tree's glow intensified, spreading outward to fill the clearing.\n\nSlowly, the fog began to lift, revealing the orchard in all its former glory. Blossoms burst forth from the branches, and the air filled with the sweet scent of fruit. Kael's music had awakened the land's magic, reminding it of the promises made so long ago.\n\nAs the first light of dawn crept over the horizon, Kael knew his mission was complete. He had protected his homeland, saving it from the brink of destruction. Though the road ahead would be long and difficult, he felt a sense of peace wash over him. The forgotten promises had been remembered, and the land would flourish once more.",
  "element_scores": {
    "character": 9.0,
    "object": 8.0,
    "concept": 9.0,
    "attribute": 8.0,
    "action": 9.0,
    "method": 8.0,
    "setting": 10.0,
    "timeframe": 8.0,
    "motivation": 9.0,
    "tone": 9.0
  },
  "creativity_scores": {
    "fluency": 9.0,
    "flexibility": 8.0,
    "originality": 8.0,
    "elaboration": 9.0,
    "usefulness": 9.0,
    "strategies": 8.0
  },
  "avg_element_score": 8.7,
  "avg_creativity_score": 8.5,
  "overall_score": 8.6,
  "model_response": "In the ruined orchard district, where centuries of thick fog had swallowed all light and hope, a street musician named Kael huddled beside a blacksmith's forge. The once-mighty forge now stood as a hollow shell, its hearth cold and dark. Kael's fingers, numb from the chill, struggled to press the strings of his lute. The melancholy notes he coaxed forth seemed to echo the despair that gripped his homeland.\n\nKael was quietly desperate, his heart heavy with the weight of forgotten promises. Generations ago, his ancestors had sworn to protect this land, to nurture its beauty and magic. But as time passed, the people forgot their vows, and the land began to wither and die. Now, at the stroke of midnight, Kael felt the urgency of his mission keenly. He had to act, to find a way to save his dying homeland.\n\nLegend spoke of a path, hidden in the stars, that would lead to the heart of the land's magic. Kael had spent countless nights studying the celestial map, memorizing the patterns. Tonight, he would follow the stars, no matter the danger, to protect the land he loved.\n\nAs he set out into the fog-shrouded orchard, the musician's footsteps were silent on the damp earth. The trees, once laden with fruit, now stood as skeletal sentinels, their branches like bony fingers reaching for the sky. Kael navigated through the maze of trunks, his eyes fixed on the stars above, his heart pounding in his chest.\n\nThe journey was long and treacherous, the fog threatening to swallow him whole at every turn. But Kael pressed on, driven by his tender brutality - a fierce determination tempered by the gentleness of his musician's soul. He would not let his homeland perish without a fight.\n\nFinally, after what seemed like hours of walking, Kael reached a clearing. In the center stood an ancient tree, its trunk glowing with a soft, ethereal light. This was the heart of the land's magic, the source of its life and vitality. Kael approached slowly, his lute at the ready.\n\nWith trembling fingers, he began to play. The music was unlike anything he had ever created before - a symphony of hope and sorrow, of forgotten promises and desperate longing. As the final notes faded away, the tree's glow intensified, spreading outward to fill the clearing.\n\nSlowly, the fog began to lift, revealing the orchard in all its former glory. Blossoms burst forth from the branches, and the air filled with the sweet scent of fruit. Kael's music had awakened the land's magic, reminding it of the promises made so long ago.\n\nAs the first light of dawn crept over the horizon, Kael knew his mission was complete. He had protected his homeland, saving it from the brink of destruction. Though the road ahead would be long and difficult, he felt a sense of peace wash over him. The forgotten promises had been remembered, and the land would flourish once more."
}
```

---

## Ground rules

* Same eval config for everyone.