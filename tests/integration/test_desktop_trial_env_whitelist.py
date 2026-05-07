from src.execution.desktop_trial_runner import build_whitelisted_env


def test_desktop_trial_env_whitelist_filters_sensitive_values():
    env = {
        "PATH": "path-value",
        "OPENAI_API_KEY": "sk-test",
        "MY_TOKEN_X": "token",
        "PASSWORD": "pw",
        "USERPROFILE": "profile",
        "RANDOM": "no",
    }

    child_env = build_whitelisted_env(env)

    assert child_env == {"PATH": "path-value", "USERPROFILE": "profile"}
