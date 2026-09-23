import os
import pytest


COMPOSE = open("docker-compose.yml", encoding="utf-8").read()


def test_r04_redis_requires_password():
    assert "--requirepass ${REDIS_PASSWORD}" in COMPOSE


def test_r04_redis_not_exposed_to_host():
    redis_block = COMPOSE.split("redis:")[1].split("postgres:")[0]
    assert "ports:" not in redis_block


def test_r04_api_uses_credentialed_redis_url():
    assert "REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0" in COMPOSE


def test_r04_datastores_on_core_network_only():
    import yaml

    doc = yaml.safe_load(COMPOSE)
    nets = doc["services"]["redis"]["networks"]
    assert nets == ["core"], f"redis must be core-only, got {nets}"
    for svc in ("postgres", "nats", "opa"):
        assert doc["services"][svc]["networks"] == ["core"]
    # Edge-facing services that have no business reaching the datastore tier.
    assert doc["services"]["ascend-lb"]["networks"] == ["edge"]
    assert doc["services"]["orion-dashboard"]["networks"] == ["edge"]
    # API bridges both tiers (serves edge, talks to core).
    api_nets = set(doc["services"]["orion-api"]["networks"])
    assert api_nets == {"edge", "core"}


def test_r04_env_template_documents_all_stack_secrets():
    example = open(".env.example", encoding="utf-8").read()
    for var in ("POSTGRES_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
                "REDIS_PASSWORD", "NATS_USER", "NATS_PASSWORD"):
        assert var in example, f"{var} missing from .env.example"
