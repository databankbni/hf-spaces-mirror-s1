def grade_episode(history, task):
    if len(history) == 0:
        return 0

    total_reward = sum([h["reward"] for h in history])
    avg_focus = sum([h["focus"] for h in history]) / len(history)
    distraction_count = sum([len(h["distractions"]) for h in history])

    score = 0

    # 🔥 1. Focus Score (40%)
    score += 0.4 * avg_focus

    # 🔥 2. Reward Score (FIXED NORMALIZATION)
    max_possible_reward = len(history) * task.reward_scale * 2.0
    reward_score = total_reward / max_possible_reward
    score += 0.4 * reward_score

    # 🔥 3. Reduced Distraction Penalty (LESS HARSH)
    score -= 0.1 * min(distraction_count / 10, 1)

    return max(0, min(score, 1))