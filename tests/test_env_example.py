from scripts.env_example import is_likely_secret, parse_env_file


def test_classifier_hits_obvious_credentials():
    for name in [
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "POSTGRES_PASSWORD",
        "JWT_SECRET",
        "STRIPE_SECRET_KEY",
        "REDIS_PWD",
        "WEBHOOK_SECRET",
        "AWS_SECRET_ACCESS_KEY",
    ]:
        assert is_likely_secret(name), name


def test_classifier_treats_id_suffix_as_meta():
    # By convention, `_ID` names are identifiers, not credential material —
    # the matching secret half (e.g. AWS_SECRET_ACCESS_KEY,
    # GOOGLE_OAUTH_CLIENT_SECRET) is where the credential lives.
    assert not is_likely_secret("AWS_ACCESS_KEY_ID")
    assert not is_likely_secret("GOOGLE_OAUTH_CLIENT_ID")


def test_classifier_ignores_obvious_config():
    for name in [
        "API_HOST",
        "API_PORT",
        "DATABASE_URL",
        "LOG_LEVEL",
        "DEBUG",
        "MAX_RETRIES",
        "MODEL_NAME",
        "REGION",
    ]:
        assert not is_likely_secret(name), name


def test_classifier_handles_false_positive_traps():
    # `AUTH` and `ACCESS` are weak — they only count when not paired with
    # a config suffix.
    assert not is_likely_secret("AUTH_REQUIRED")
    assert not is_likely_secret("AUTH_METHOD")
    assert not is_likely_secret("LOG_ACCESS_EVENTS")
    assert not is_likely_secret("SESSION_MAX_AGE_SECONDS")
    assert not is_likely_secret("MAX_MODELS_PER_SESSION")
    assert not is_likely_secret("JWT_ALGORITHM")
    assert not is_likely_secret("TOKEN_NAME")
    assert not is_likely_secret("KEY_PATH")


def test_classifier_keeps_hard_secret_with_file_suffix():
    # SECRET_FILE / TOKEN_FILE point at a file *containing* the credential —
    # still a secret reference, not config.
    assert is_likely_secret("SESSION_SECRET_FILE")
    assert is_likely_secret("GH_TOKEN_FILE")


def test_parse_env_file_strips_comments_and_blanks():
    text = """\
# A comment
OPENAI_API_KEY=sk-...
API_HOST=localhost

  export DEBUG=true
not a var line
DUPLICATE=1
DUPLICATE=2
"""
    parsed = parse_env_file(text)
    names = [n for n, _ in parsed]
    assert names == ["OPENAI_API_KEY", "API_HOST", "DEBUG", "DUPLICATE"]
    secrets = dict(parsed)
    assert secrets["OPENAI_API_KEY"] is True
    assert secrets["API_HOST"] is False
    assert secrets["DEBUG"] is False
    assert secrets["DUPLICATE"] is False


def test_parse_env_file_handles_quoted_and_padded_values():
    text = 'FOO  =  "bar"\nexport BAZ=qux\n'
    parsed = parse_env_file(text)
    assert [n for n, _ in parsed] == ["FOO", "BAZ"]
