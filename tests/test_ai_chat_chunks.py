"""Tests for ai_chat_chunks batch transport."""

from unittest.mock import patch

from script_scaffold.search import ai_chat_chunks


def test_ai_chat_chunks_sequences_prompts():
    with patch("script_scaffold.search.ai_chat") as mock_chat:
        mock_chat.side_effect = ['{"ok": true}', None]
        outcomes = ai_chat_chunks(["prompt one", "prompt two"], route="batch", json_mode=True)
    assert mock_chat.call_count == 2
    assert outcomes[0].triggered is True
    assert outcomes[0].reply == '{"ok": true}'
    assert outcomes[1].triggered is False
    assert outcomes[1].skip_reason == "no_api_key_or_call_failed"
