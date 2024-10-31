import pytest
from model import (
    BinaryClassificationResult,
    CountingResult,
    Label,
    ModeEnum,
    ResultTypeEnum,
    Source,
)

from app.core.utils import create_iq, prefixed_ksuid


class TestCreateIQE:
    def setup_method(self):
        self.confidence_threshold = 0.75

    def test_create_binary_iqe(self):
        """Test creating a basic binary IQE."""
        iqe = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.BINARY,
            mode_configuration=None,
            result_value=0,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert iqe.result_type == ResultTypeEnum.binary_classification
        assert isinstance(iqe.result, BinaryClassificationResult)
        assert iqe.result.source == Source.ALGORITHM
        assert iqe.result.label == Label.YES

    def test_create_count_iqe(self):
        """Test creating a basic count IQE."""
        count_value = 2
        iqe = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.COUNT,
            mode_configuration={"max_count": 5},
            result_value=count_value,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert iqe.result_type == ResultTypeEnum.counting
        assert isinstance(iqe.result, CountingResult)
        assert iqe.result.source == Source.ALGORITHM
        assert iqe.result.count == count_value
        assert not iqe.result.greater_than_max

    def test_create_count_iqe_greater_than_max(self):
        """Test creating a count IQE with count greater than the max count."""
        count_value = 6
        max_count_value = 5
        iqe = create_iq(
            detector_id=prefixed_ksuid("det_"),
            mode=ModeEnum.COUNT,
            mode_configuration={"max_count": max_count_value},
            result_value=count_value,
            confidence=0.8,
            confidence_threshold=self.confidence_threshold,
            query="Test query",
        )

        assert iqe.result_type == ResultTypeEnum.counting
        assert isinstance(iqe.result, CountingResult)
        assert iqe.result.source == Source.ALGORITHM
        assert iqe.result.greater_than_max
        assert iqe.result.count == max_count_value

    def test_create_multiclass_iqe(self):
        """Test creating a basic multiclass IQE."""
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

    def test_create_count_iqe_without_configuration(self):
        """Test creating a count IQE with no mode_configuration."""
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
