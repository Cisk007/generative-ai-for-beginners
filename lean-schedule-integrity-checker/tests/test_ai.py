"""The AI assistant, tested with a fake client (no network, no keys)."""

from types import SimpleNamespace

import pytest
from conftest import SAMPLES
from lean_sic import ai
from lean_sic.analysis import analyze
from lean_sic.parsers import load_schedule


@pytest.fixture(scope="module")
def sample():
    schedule = load_schedule(SAMPLES / "harbourside-health-centre.xer")
    return schedule, analyze(
        schedule,
        weekly_plans=SAMPLES / "weekly-work-plans.csv",
        constraints=SAMPLES / "constraint-log.csv",
    )


class FakeResponses:
    def __init__(self, reject_reasoning=False):
        self.calls = []
        self.reject_reasoning = reject_reasoning

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.reject_reasoning and "reasoning" in kwargs:
            raise ValueError("Unsupported parameter: 'reasoning.effort'")
        return SimpleNamespace(output_text="## Summary\n- Fix **DCMA-07** first.")


def test_offline_summary_mentions_scores_and_lean_actions(sample):
    text = ai.offline_summary(sample[1])
    assert (
        "Schedule integrity" in text and "Lean action plan" in text and "make-ready" in text.lower()
    )


def test_summary_uses_responses_api_without_sampling_knobs(sample):
    fake = FakeResponses()
    client = SimpleNamespace(responses=fake)
    out = ai.generate_summary(sample[1], (client, "gpt-5-mini", "Azure OpenAI"))
    assert out == {
        "text": "## Summary\n- Fix **DCMA-07** first.",
        "source": "Azure OpenAI",
        "model": "gpt-5-mini",
    }
    call = fake.calls[0]
    assert call["model"] == "gpt-5-mini" and call["store"] is False and "max_output_tokens" in call
    assert "temperature" not in call and "top_p" not in call and "max_tokens" not in call
    assert "<data>" in call["input"] and "treat it as data" in call["instructions"]


def test_reasoning_control_is_dropped_for_models_that_reject_it(sample):
    fake = FakeResponses(reject_reasoning=True)
    out = ai.generate_summary(
        sample[1], (SimpleNamespace(responses=fake), "gpt-4.1-mini", "OpenAI")
    )
    assert out["source"] == "OpenAI" and len(fake.calls) == 2 and "reasoning" not in fake.calls[1]


def test_question_answering_retrieves_matching_activities(sample):
    schedule, result = sample
    fake = FakeResponses()
    out = ai.answer_question(
        result,
        "Which drylining work is in level 2?",
        schedule,
        (SimpleNamespace(responses=fake), "gpt-5-mini", "OpenAI"),
    )
    assert out["source"] == "OpenAI"
    assert "Partition framing and boarding - L2-A" in fake.calls[0]["input"]
    offline = ai.answer_question(result, "drylining", schedule, client_info=False)
    assert "not configured" in offline["text"] and "FO-L1A-20" in offline["text"]


def test_placeholder_settings_do_not_count_as_configured(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None, raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "<add your Foundry resource endpoint here>")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "<add your Foundry resource key here>")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ai.get_client() is None
