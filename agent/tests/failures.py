"""Failures the tests stage at a chosen moment."""


def fail_once(monkeypatch, module, name, error, carry_out=False):
    """Make the next call to a function raise an error, once it has been carried out
    if asked, as a crash or a lost connection at that moment would."""
    function = getattr(module, name)

    def then_fail(*args, **kwargs):
        monkeypatch.setattr(module, name, function)
        if carry_out:
            function(*args, **kwargs)
        raise error

    monkeypatch.setattr(module, name, then_fail)
