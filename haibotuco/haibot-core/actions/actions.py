from typing import Any

from rasa_sdk import Action, Tracker
from rasa_sdk.events import FollowupAction, SlotSet
from rasa_sdk.executor import CollectingDispatcher


class ActionHandleSelectOption(Action):
    ROUTES = {
        "utter_options_list": {
            "1": "utter_emotional_control",
            "2": "utter_behavioral_control",
            "3": "utter_assertive_communication",
            "4": "utter_psychoeducational_activity",
        },
        "utter_emotional_control_more_info_questions": {
            "1": "utter_emotional_control_info_tdah",
            "2": "utter_emotional_control_info_caregiver",
        },
        "utter_behavioral_control_more_info_questions": {
            "1": "utter_behavioral_control_info_tdah",
            "2": "utter_behavioral_control_info_caregiver",
        },
    }
    IGNORED_ACTIONS = {
        "action_listen",
        "action_handle_select_option",
        "action_prepare_survey_comment",
    }

    def name(self) -> str:
        return "action_handle_select_option"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: dict[str, Any],
    ) -> list[dict[str, Any]]:
        option_number = self._resolve_option_number(tracker)
        last_action = self._last_relevant_action(tracker)

        response_name = self.ROUTES.get(last_action, {}).get(option_number)
        if response_name:
            return [SlotSet("option_number", None), FollowupAction(response_name)]

        dispatcher.utter_message(response="utter_choose_option")
        dispatcher.utter_message(response="utter_options_list")
        return [SlotSet("option_number", None)]

    @staticmethod
    def _last_relevant_action(tracker: Tracker) -> str | None:
        for event in reversed(tracker.events):
            if event.get("event") != "action":
                continue
            action_name = event.get("name")
            if action_name in ActionHandleSelectOption.IGNORED_ACTIONS:
                continue
            return action_name
        return None

    @staticmethod
    def _resolve_option_number(tracker: Tracker) -> str | None:
        entities = tracker.latest_message.get("entities", [])
        for entity in entities:
            if entity.get("entity") == "option_number":
                value = entity.get("value")
                if value is not None:
                    return str(value)

        text = (tracker.latest_message.get("text") or "").strip().lower()
        text_map = {
            "1": "1",
            "uno": "1",
            "2": "2",
            "dos": "2",
            "3": "3",
            "tres": "3",
            "4": "4",
            "cuatro": "4",
        }
        return text_map.get(text)


class ActionPrepareSurveyComment(Action):
    def name(self) -> str:
        return "action_prepare_survey_comment"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [SlotSet("survey_comment", None)]

