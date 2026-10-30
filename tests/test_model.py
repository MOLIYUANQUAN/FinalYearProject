"""她的脑子：默认 GPT-5（推理模型：给思考力度、回答短一点，不传 temperature）；账号用不了就退回能用的。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import openai

import src.agent as agent


class ModelTests(unittest.TestCase):
    def tearDown(self) -> None:
        agent._active_model = agent.DEFAULT_MODEL

    def test_reasoning_models_get_effort_not_temperature(self) -> None:
        settings = agent.model_settings("gpt-5")
        self.assertIsNone(settings.temperature)
        self.assertEqual(settings.reasoning.effort, agent.REASONING_EFFORT)
        self.assertEqual(settings.verbosity, "low")
        self.assertEqual(agent.model_settings("gpt-4.1-mini").temperature, 0.2)

    def test_default_is_the_stronger_model(self) -> None:
        self.assertEqual(agent.DEFAULT_MODEL, "gpt-5")
        built = agent.create_assistant()
        self.assertEqual(built.model, "gpt-5")
        self.assertIsNone(built.model_settings.temperature)

    def test_falls_back_when_the_account_cannot_use_it(self) -> None:
        missing = openai.NotFoundError("no such model", response=MagicMock(status_code=404), body=None)
        client = MagicMock()
        client.models.retrieve.side_effect = missing
        with patch.object(openai, "OpenAI", return_value=client):
            self.assertEqual(agent.verify_model(), agent.FALLBACK_MODEL)
        built = agent.create_assistant()
        self.assertEqual(built.model, agent.FALLBACK_MODEL)
        self.assertEqual(built.model_settings.temperature, 0.2)

    def test_network_trouble_keeps_the_default(self) -> None:
        client = MagicMock()
        client.models.retrieve.side_effect = RuntimeError("offline")
        with patch.object(openai, "OpenAI", return_value=client):
            self.assertEqual(agent.verify_model(), "gpt-5")


if __name__ == "__main__":
    unittest.main()
