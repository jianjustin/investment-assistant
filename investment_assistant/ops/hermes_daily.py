"""Backwards-compat entry point. Implementation moved to investment_assistant.tasks.daily."""
from investment_assistant.tasks.daily import main  # noqa: F401

if __name__ == "__main__":
    main()
