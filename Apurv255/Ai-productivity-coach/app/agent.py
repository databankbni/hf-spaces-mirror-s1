from app.models import Action
import random
import json
import os


class FocusAgent:

    def __init__(self):

        self.q_table = {}

        self.actions = [
            "continue",
            "take_break",
            "block_distraction"
        ]

        self.alpha = 0.1
        self.gamma = 0.9
        self.epsilon = 0.4

        # q_table.json is stored in the project root
        self.q_table_path = os.path.abspath(
            os.path.join(
                os.path.dirname(
                    os.path.abspath(__file__)
                ),
                "..",
                "q_table.json"
            )
        )

        self.load_q_table()


    # -----------------------------------------
    # STATE GENERALIZATION
    # -----------------------------------------
    def get_state_key(self, state):

        focus = round(
            state["focus_level"],
            1
        )

        fatigue = round(
            state["fatigue"],
            1
        )

        distractions = len(
            state["distractions"]
        )

        deadline = max(
            state["deadline"],
            1
        )

        time_ratio = round(
            state["time_spent"] / deadline,
            1
        )

        return (
            focus,
            fatigue,
            distractions,
            time_ratio
        )


    # -----------------------------------------
    # FIND NEAREST TRAINED STATE
    # -----------------------------------------
    def find_nearest_state(self, state_key):

        if not self.q_table:
            return None

        best_state = None
        best_distance = float("inf")

        for trained_state in self.q_table.keys():

            # State:
            # (focus, fatigue, distractions, time_ratio)

            focus_distance = (
                trained_state[0]
                - state_key[0]
            ) ** 2

            fatigue_distance = (
                trained_state[1]
                - state_key[1]
            ) ** 2

            distraction_distance = (
                trained_state[2]
                - state_key[2]
            ) ** 2

            time_distance = (
                trained_state[3]
                - state_key[3]
            ) ** 2

            distance = (
                focus_distance
                + fatigue_distance
                + distraction_distance
                + time_distance
            )

            if distance < best_distance:

                best_distance = distance
                best_state = trained_state

        return best_state


    # -----------------------------------------
    # GET Q-VALUES FOR CURRENT STATE
    # -----------------------------------------
    def get_q_values(self, state):

        state_key = self.get_state_key(
            state
        )

        # Exact trained state
        if state_key in self.q_table:

            return self.q_table[
                state_key
            ]

        # Unseen state -> nearest trained state
        nearest_state = (
            self.find_nearest_state(
                state_key
            )
        )

        if nearest_state is not None:

            return self.q_table[
                nearest_state
            ]

        # No trained model available
        return {}


    # -----------------------------------------
    # DECISION
    # -----------------------------------------
    def decide(
        self,
        state,
        training=True
    ):

        state_key = self.get_state_key(
            state
        )


        # -----------------------------------------
        # EXACT STATE EXISTS
        # -----------------------------------------
        if state_key in self.q_table:

            policy_state = state_key

            reason_prefix = (
                "Using learned policy"
            )


        # -----------------------------------------
        # UNSEEN STATE
        # -----------------------------------------
        else:

            nearest_state = (
                self.find_nearest_state(
                    state_key
                )
            )

            if nearest_state is not None:

                policy_state = nearest_state

                reason_prefix = (
                    "Using nearest learned state"
                )

            else:

                policy_state = None

                reason_prefix = (
                    "No trained state available"
                )


        # -----------------------------------------
        # NO Q-TABLE AVAILABLE
        # -----------------------------------------
        if policy_state is None:

            action_type = "continue"

            reason = (
                "No trained Q-table available"
            )


        else:

            q_values = self.q_table[
                policy_state
            ]


            # -----------------------------------------
            # EXPLORATION
            # -----------------------------------------
            if (
                training
                and random.random()
                < self.epsilon
            ):

                action_type = random.choice(
                    self.actions
                )

                reason = (
                    f"{reason_prefix} - Exploring"
                )


            # -----------------------------------------
            # EXPLOITATION
            # -----------------------------------------
            else:

                max_q = max(
                    q_values.values()
                )

                best_actions = [
                    action
                    for action, q_value
                    in q_values.items()
                    if q_value == max_q
                ]

                action_type = random.choice(
                    best_actions
                )

                reason = (
                    f"{reason_prefix} - "
                    "Exploiting learned policy"
                )


        # -----------------------------------------
        # CREATE ACTION OBJECT
        # -----------------------------------------
        if action_type == "block_distraction":

            target = (
                state["distractions"][0]
                if state["distractions"]
                else "youtube"
            )

            action = Action(
                action=action_type,
                target=target
            )

        else:

            action = Action(
                action=action_type
            )


        return action, reason


    # -----------------------------------------
    # Q-LEARNING UPDATE
    # -----------------------------------------
    def update(
        self,
        prev_state,
        action,
        reward,
        next_state
    ):

        current_state_key = (
            self.get_state_key(
                prev_state
            )
        )

        next_state_key = (
            self.get_state_key(
                next_state
            )
        )


        if current_state_key not in self.q_table:

            self.q_table[
                current_state_key
            ] = {
                action_name: 0
                for action_name
                in self.actions
            }


        if next_state_key not in self.q_table:

            self.q_table[
                next_state_key
            ] = {
                action_name: 0
                for action_name
                in self.actions
            }


        current_q = self.q_table[
            current_state_key
        ][action]


        max_next_q = max(
            self.q_table[
                next_state_key
            ].values()
        )


        new_q = (
            current_q
            + self.alpha
            * (
                reward
                + self.gamma
                * max_next_q
                - current_q
            )
        )


        self.q_table[
            current_state_key
        ][action] = new_q


        # Gradually reduce exploration
        self.epsilon = max(
            0.05,
            self.epsilon * 0.992
        )


    # -----------------------------------------
    # TRAIN
    # -----------------------------------------
    def train(
        self,
        env,
        episodes=300
    ):

        print(
            f"Training for {episodes} episodes..."
        )


        for episode in range(
            episodes
        ):

            state = env.reset()

            state_dict = state.dict()

            done = False
            steps = 0


            while (
                not done
                and steps < 50
            ):

                action, _ = self.decide(
                    state_dict,
                    training=True
                )


                next_state, reward, done, _ = (
                    env.step(action)
                )


                next_state_dict = (
                    next_state.dict()
                )


                self.update(
                    prev_state=state_dict,
                    action=action.action,
                    reward=reward.value,
                    next_state=next_state_dict
                )


                state_dict = next_state_dict

                steps += 1


            if episode % 50 == 0:

                print(
                    f"Episode {episode}/{episodes} "
                    f"| epsilon={self.epsilon:.3f}"
                )


        self.save_q_table()


        print(
            "Training complete. Q-table saved."
        )


    # -----------------------------------------
    # SCORE
    # -----------------------------------------
    def get_score(self, env):

        state = env.reset()

        state_dict = state.dict()

        done = False

        total_reward = 0
        total_focus = 0
        total_distractions = 0
        steps = 0


        self.freeze()


        while (
            not done
            and steps < 50
        ):

            action, _ = self.decide(
                state_dict,
                training=False
            )


            next_state, reward, done, _ = (
                env.step(action)
            )


            next_state_dict = (
                next_state.dict()
            )


            total_reward += reward.value


            total_focus += (
                next_state_dict[
                    "focus_level"
                ]
            )


            total_distractions += len(
                next_state_dict[
                    "distractions"
                ]
            )


            state_dict = next_state_dict

            steps += 1


        avg_focus = (
            total_focus
            / max(steps, 1)
        )


        avg_reward = (
            total_reward
            / max(steps, 1)
        )


        score = round(
            min(
                1.0,
                max(
                    0.0,
                    avg_focus * 0.6
                    + avg_reward * 0.4
                )
            ),
            4
        )


        return {
            "score": score,

            "avg_focus": round(
                avg_focus,
                4
            ),

            "total_reward": round(
                total_reward,
                4
            ),

            "total_distractions":
                total_distractions,

            "steps":
                steps,

            "grade":
                "A"
                if score > 0.75
                else "B"
                if score > 0.5
                else "C"
        }


    # -----------------------------------------
    # FREEZE EXPLORATION
    # -----------------------------------------
    def freeze(self):

        self.epsilon = 0.05


    # -----------------------------------------
    # SAVE Q-TABLE
    # -----------------------------------------
    def save_q_table(self):

        serializable_q = {
            str(key): value
            for key, value
            in self.q_table.items()
        }


        with open(
            self.q_table_path,
            "w"
        ) as file:

            json.dump(
                serializable_q,
                file,
                indent=2
            )


    # -----------------------------------------
    # LOAD Q-TABLE
    # -----------------------------------------
    def load_q_table(self):

        try:

            with open(
                self.q_table_path,
                "r"
            ) as file:

                raw_q = json.load(
                    file
                )


            self.q_table = {}


            for key, value in raw_q.items():

                key = key.strip(
                    "()"
                )

                parts = key.split(",")


                parsed_key = tuple(
                    float(
                        part.strip()
                    )
                    for part in parts
                )


                self.q_table[
                    parsed_key
                ] = value


            print(
                f"Loaded Q-table: "
                f"{len(self.q_table)} states"
            )


        except (
            FileNotFoundError,
            json.JSONDecodeError,
            ValueError,
            TypeError
        ):

            self.q_table = {}


            print(
                "No valid Q-table found. "
                "Starting with an empty Q-table."
            )