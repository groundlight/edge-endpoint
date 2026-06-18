from app.core.utils import ModelInfoWithBinary, parse_model_info


def _base_response(**overrides) -> dict:
    response = {
        "pipeline_config": "primary_pipeline_config",
        "predictor_metadata": '{"text_query":"x","mode":"BINARY"}',
        "model_binary_id": "primary_binary_id",
        "model_binary_url": "https://example/primary",
        "oodd_pipeline_config": "oodd_pipeline_config",
        "oodd_model_binary_id": "oodd_binary_id",
        "oodd_model_binary_url": "https://example/oodd",
    }
    response.update(overrides)
    return response


class TestParseModelInfo:
    def test_minimal_compatible_true(self):
        edge_info, oodd_info = parse_model_info(_base_response(minimal_compatible=True))
        assert isinstance(edge_info, ModelInfoWithBinary)
        assert edge_info.minimal_compatible is True
        assert oodd_info.minimal_compatible is False

    def test_minimal_compatible_false(self):
        edge_info, oodd_info = parse_model_info(_base_response(minimal_compatible=False))
        assert edge_info.minimal_compatible is False
        assert oodd_info.minimal_compatible is False

    def test_minimal_compatible_missing_defaults_false(self):
        """When the cloud is older than the edge endpoint, the field is absent."""
        edge_info, oodd_info = parse_model_info(_base_response())
        assert edge_info.minimal_compatible is False
        assert oodd_info.minimal_compatible is False
