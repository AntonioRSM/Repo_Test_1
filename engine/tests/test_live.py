"""Against a real local server. Run with: uv run pytest -m live"""

import asyncio

import pytest

from vault_engine.config import ModelRef
from vault_engine.providers import ProviderClient, discover

pytestmark = pytest.mark.live


def first_embedding_model():
    statuses = asyncio.run(discover())
    for status in statuses:
        if status.online:
            for model in status.models:
                if "embedding" in model.kinds:
                    return ModelRef(provider=status.provider, model=model.id)
    pytest.skip("no local embedding model available")


def test_discovery_and_real_embeddings():
    ref = first_embedding_model()
    client = ProviderClient({})
    vectors = asyncio.run(client.embed(ref, ["contratto di fornitura", "supply contract", "ricetta della pizza"]))
    import numpy as np

    v = np.array(vectors)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    # Cross-lingual pair is closer than the unrelated sentence.
    assert v[0] @ v[1] > v[0] @ v[2]
