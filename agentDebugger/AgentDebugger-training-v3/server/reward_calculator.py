
import difflib
import re
from dataclasses import dataclass
from typing import Optional
from server.models import StructuredAgentOutput


@dataclass
class RewardBreakdown:
    format_compliance: float     
    hypothesis_quality: float    
    localization: float          
    fix_quality: float           
    semantic_similarity: float   
    efficiency_potential: float  
    penalties: float
    total: float


class DebugRewardCalculator:

    MAX_TURNS = 5

    def compute_turn_reward(
        self,
        agent_output: StructuredAgentOutput,
        ground_truth: dict,
        test_results: dict,
        turn_number: int,
    ) -> RewardBreakdown:

        
        
        
        if agent_output.valid:
            format_score = 0.10
        else:
            
            fields_present = sum([
                len(agent_output.observation) > 5,
                len(agent_output.hypothesis) > 10,
                agent_output.confidence in {"low", "medium", "high"},
                agent_output.action in {"inspect_lines", "run_tests", "propose_fix",
                                        "request_context", "give_up"},
                len(agent_output.detail) > 0,
            ])
            format_score = -0.25 + (fields_present * 0.04)  

        
        
        
        
        hypothesis_score = 0.0
        hypothesis = agent_output.hypothesis

        if len(hypothesis.split()) >= 20:
            hypothesis_score += 0.05   

        
        if re.search(r'[`\'"<>!=+\-*/]', hypothesis):
            hypothesis_score += 0.05

        
        if re.search(r'\bline\s+\d+\b|\b\d+\b', hypothesis):
            hypothesis_score += 0.05

        
        obs_words = set(agent_output.observation.lower().split())
        hyp_words = set(hypothesis.lower().split())
        overlap = len(obs_words & hyp_words) / max(len(obs_words), 1)
        if overlap > 0.15:
            hypothesis_score += 0.05

        
        
        if agent_output.action == "propose_fix":
            tests_pass = test_results.get("passed", 0) == test_results.get("total", 1)
            if agent_output.confidence == "high" and tests_pass:
                hypothesis_score += 0.05   
            elif agent_output.confidence == "high" and not tests_pass:
                hypothesis_score -= 0.05   
            elif agent_output.confidence == "low" and tests_pass:
                hypothesis_score += 0.02   

        hypothesis_score = max(0.0, min(hypothesis_score, 0.20))

        
        
        localization_score = 0.0
        bug_function = ground_truth.get("bug_function", "").lower()
        bug_line = str(ground_truth.get("bug_line", -1))

        combined_text = (agent_output.hypothesis + " " + agent_output.detail).lower()

        if bug_function and bug_function in combined_text:
            localization_score += 0.08

        if bug_line != "-1" and bug_line in agent_output.hypothesis:
            localization_score += 0.07

        localization_score = min(localization_score, 0.15)

        
        
        
        total_tests = test_results.get("total", 0)
        passed_tests = test_results.get("passed", 0)
        fix_score = 0.0

        if total_tests > 0 and agent_output.action == "propose_fix":
            pass_rate = passed_tests / total_tests
            if pass_rate == 1.0:
                fix_score = 0.35      
            elif pass_rate >= 0.75:
                fix_score = 0.20      
            elif pass_rate >= 0.50:
                fix_score = 0.12      
            elif pass_rate > 0.0:
                fix_score = 0.05      
            

        
        
        
        semantic_score = 0.0
        proposed = agent_output.detail
        canonical = ground_truth.get("canonical_fix_code", "")

        if proposed and canonical and agent_output.action == "propose_fix":
            similarity = difflib.SequenceMatcher(None, proposed, canonical).ratio()
            if similarity >= 0.85:
                semantic_score = 0.10
            elif similarity >= 0.65:
                semantic_score = 0.05
            elif similarity >= 0.40:
                semantic_score = 0.02
            

        
        
        
        
        
        remaining_turns = self.MAX_TURNS - turn_number
        efficiency_potential = 0.02 * remaining_turns  

        
        penalties = 0.0

        
        if test_results.get("newly_broken", 0) > 0:
            penalties -= 0.20

        
        if agent_output.action == "give_up":
            penalties -= 0.15

        
        if agent_output.action == "invalid":
            penalties -= 0.10

        
        if not agent_output.valid:
            penalties -= 0.10

        
        raw_total = (
            format_score
            + hypothesis_score
            + localization_score
            + fix_score
            + semantic_score
            + efficiency_potential
            + penalties
        )

        
        total = max(raw_total, -0.5)

        return RewardBreakdown(
            format_compliance=round(format_score, 4),
            hypothesis_quality=round(hypothesis_score, 4),
            localization=round(localization_score, 4),
            fix_quality=round(fix_score, 4),
            semantic_similarity=round(semantic_score, 4),
            efficiency_potential=round(efficiency_potential, 4),
            penalties=round(penalties, 4),
            total=round(total, 4),
        )

    def compute_episode_reward(self, trajectory: list[dict]) -> float:
        if not trajectory:
            return 0.0

        total = 0.0
        discount = 1.0

        for turn in trajectory:
            total += discount * turn["reward"].total
            discount *= 0.9

        
        solved = any(t["reward"].fix_quality >= 0.35 for t in trajectory)
        if solved:
            total += 0.20

        return round(total, 4)

    def get_reward_breakdown_for_logging(self, trajectory: list[dict]) -> dict:
        if not trajectory:
            return {}

        components = [
            "format_compliance", "hypothesis_quality", "localization",
            "fix_quality", "semantic_similarity", "efficiency_potential", "penalties"
        ]

        return {
            f"reward/{c}": round(
                sum(t["reward"].__dict__[c] for t in trajectory) / len(trajectory), 4
            )
            for c in components
        }
