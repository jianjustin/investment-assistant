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
