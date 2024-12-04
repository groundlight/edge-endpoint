import pytest
from model import (
    BinaryClassificationResult,
    CountingResult,
    Label,
    ModeEnum,
    ResultTypeEnum,
    Source,
)

from app.core.utils import (
    ModelInfoBase,
    ModelInfoNoBinary,
    ModelInfoWithBinary,
    create_iq,
    parse_model_info,
    prefixed_ksuid,
)


class TestCreateIQ:
    def setup_method(self):
        self.confidence_threshold = 0.75

    def test_create_binary_iq(self):
        """Test creating a basic binary IQ."""
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.BINARY,
            mode_configuration=None,
            result_value=0,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert "iq_" in iq.id
        assert iq.result_type == ResultTypeEnum.binary_classification
        assert isinstance(iq.result, BinaryClassificationResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.label == Label.YES

    def test_create_count_iq(self):
        """Test creating a basic count IQ."""
        count_value = 2
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.COUNT,
            mode_configuration={"max_count": 5},
            result_value=count_value,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert "iq_" in iq.id
        assert iq.result_type == ResultTypeEnum.counting
        assert isinstance(iq.result, CountingResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.count == count_value
        assert not iq.result.greater_than_max

    def test_create_count_iq_greater_than_max(self):
        """Test creating a count IQ with count greater than the max count."""
        count_value = 6
        max_count_value = 5
        iq = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.COUNT,
            mode_configuration={"max_count": max_count_value},
            result_value=count_value,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert iq.result_type == ResultTypeEnum.counting
        assert isinstance(iq.result, CountingResult)
        assert iq.result.source == Source.ALGORITHM
        assert iq.result.greater_than_max
        assert iq.result.count == max_count_value

    def test_create_multiclass_iq(self):
        """Test creating a basic multiclass IQ."""
        # TODO this test should test the real functionality once multiclass is supported
        with pytest.raises(
            NotImplementedError, match="Multiclass functionality is not yet implemented for the edge endpoint."
        ):
            create_iq(
                detector_id=prefixed_ksuid("det_"),
                mode=ModeEnum.MULTI_CLASS,
                mode_configuration={},
                result_value=1,
                confidence=0.8,
                confidence_threshold=self.confidence_threshold,
                query="Test query",
            )

    def test_create_count_iq_without_configuration(self):
        """Test creating a count IQ with no mode_configuration."""
        with pytest.raises(ValueError, match="mode_configuration for Counting detector shouldn't be None."):
            create_iq(
                detector_id=prefixed_ksuid("det_"),
                mode=ModeEnum.COUNT,
                mode_configuration=None,
                result_value=1,
                confidence=0.8,
                confidence_threshold=self.confidence_threshold,
                query="Test query",
            )


class TestParseModelInfo:
    def test_parse_with_binary(self):
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "model_binary_id": "test_binary_id",
            "model_binary_url": "test_binary_url",
        }
        model_info = parse_model_info(model_info)

        assert isinstance(model_info, ModelInfoBase)
        assert isinstance(model_info, ModelInfoWithBinary)

    def test_parse_no_binary(self):
        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
            "model_binary_id": None,
            "model_binary_url": None,
        }
        model_info = parse_model_info(model_info)
        assert isinstance(model_info, ModelInfoBase)
        assert isinstance(model_info, ModelInfoNoBinary)

        model_info = {
            "pipeline_config": "test_pipeline_config",
            "predictor_metadata": "test_metadata",
        }
        model_info = parse_model_info(model_info)
        assert isinstance(model_info, ModelInfoBase)
        assert isinstance(model_info, ModelInfoNoBinary)
