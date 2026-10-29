from investment_assistant.tasks import catalog
from investment_assistant.tasks.scheduler import REGISTRY


def test_every_registered_job_is_described():
    for name in REGISTRY:
        info = catalog.describe(name)
        assert info is not None, name
        assert info['title'] and info['goal'] and info['manual_note'], name
        assert len(info['details']) >= 1, name


def test_unknown_job_has_no_description():
    assert catalog.describe('nope') is None


def test_workbench_description_mentions_review_cards():
    """v2.7 §9: the batch now has a retro stage (复盘卡)."""
    info = catalog.describe('workbench')
    text = ' '.join(info['details'])
    assert '复盘卡' in text and 'retro' in text
    assert text.index('复盘卡') < text.index('推送 Discord')
