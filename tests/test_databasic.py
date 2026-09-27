import databasic


def test_make_greeting_without_name():
    assert databasic.make_greeting() == "Hello, world!"


def test_make_greeting_with_name():
    assert databasic.make_greeting("Shrek") == "Hello, Shrek!"
